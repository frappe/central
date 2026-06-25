"""Unit tests for the Register Atlas orchestration (central/spec/TUNNEL.md).

The Atlas calls (admin_ping / provision_tunnel / confirm_tunnel) and the hub scripts
(run_host_task) are mocked — these assert the orchestration: the step sequence, the
payload Central pushes, IP allocation, the scoped service user, status transitions,
and the lockout-safe rollback at each failure point before confirm."""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.atlas import (
	SERVICE_ROLE,
	AtlasClient,
	TunnelRegistrationError,
	register_atlas,
	remove_tunnel,
)

PROVISION_RETURN = {"wg_public_key": "SPOKEPUBKEY=", "listen_port": 51820, "tunnel_ip": "10.88.0.2"}
PLAIN_USER_EMAIL = "register-plain@example.com"


def _set_hub(active: bool = True) -> None:
	frappe.db.set_single_value("Central Tunnel Settings", "tunnel_cidr", "10.88.0.0/16")
	frappe.db.set_single_value("Central Tunnel Settings", "hub_public_key", "HUBPUBKEY=")
	frappe.db.set_single_value("Central Tunnel Settings", "hub_endpoint", "203.0.113.1:51820")
	frappe.db.set_single_value("Central Tunnel Settings", "hub_status", "Active" if active else "Uninitialized")


def _make_plain_user() -> str:
	if frappe.db.exists("User", PLAIN_USER_EMAIL):
		user = frappe.get_doc("User", PLAIN_USER_EMAIL)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": PLAIN_USER_EMAIL,
				"first_name": "Plain",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	for role_row in list(user.get("roles") or []):
		user.remove(role_row)
	user.save(ignore_permissions=True)
	return user.name


class TestAtlasRegister(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		# register_atlas commits mid-flow (host tasks, User creation), so its rows
		# survive IntegrationTestCase's rollback. Wipe them before each test for a
		# deterministic allocation baseline, and again after (committed) so the suite
		# leaves no residue on the dev site.
		self._wipe()
		self.addCleanup(self._wipe, commit=True)
		self.addCleanup(frappe.set_user, "Administrator")
		_set_hub(active=True)

	def _wipe(self, commit: bool = False) -> None:
		"""Delete every Atlas Instance + per-Atlas service user — instances first to
		drop the service_user link, then the users."""
		for name in frappe.get_all("Atlas Instance", pluck="name"):
			frappe.delete_doc("Atlas Instance", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("User", filters={"name": ["like", "atlas-%@%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True, ignore_permissions=True)
		if commit:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- durably remove rows register_atlas committed mid-flow

	def make_instance(self, region: str, **overrides):
		if frappe.db.exists("Atlas Instance", region):
			frappe.delete_doc("Atlas Instance", region, force=True, ignore_permissions=True)
		values = {
			"doctype": "Atlas Instance",
			"region": region,
			"base_url": "https://blr.atlas.example.test",
			"status": "Active",
			"api_key": "admin_key",
			"api_secret": "admin_secret",
			**overrides,
		}
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def _patched(self):
		"""Patch the three Atlas calls + the hub runner; return the patch context."""
		return (
			patch.object(AtlasClient, "admin_ping", return_value={"message": "pong"}),
			patch.object(AtlasClient, "provision_tunnel", return_value=dict(PROVISION_RETURN)),
			patch.object(AtlasClient, "confirm_tunnel", return_value={"tunnel_status": "Active"}),
			patch("central.integrations.atlas.run_host_task", return_value=MagicMock()),
		)

	# ----- happy path ------------------------------------------------------

	def test_register_happy_path(self) -> None:
		instance = self.make_instance("blr-happy")
		ping, provision, confirm, host_task = self._patched()
		with ping as admin_ping, provision as provision_tunnel, confirm as confirm_tunnel, host_task as run_host_task:
			out = register_atlas(instance)

		self.assertEqual(out["tunnel_status"], "Active")
		self.assertEqual(out["tunnel_ip"], "10.88.0.2")

		instance.reload()
		self.assertEqual(instance.tunnel_status, "Active")
		self.assertEqual(instance.tunnel_ip, "10.88.0.2")
		self.assertEqual(instance.tunnel_url, "https://10.88.0.2")
		self.assertEqual(instance.peer_public_key, "SPOKEPUBKEY=")
		# peer_endpoint = host of base_url : listen port.
		self.assertEqual(instance.peer_endpoint, "blr.atlas.example.test:51820")
		self.assertTrue(instance.atlas_id)

		# provision_tunnel got the hub identity + allocated ip + pushed service creds.
		payload = provision_tunnel.call_args.args[1]
		self.assertEqual(payload["hub_public_key"], "HUBPUBKEY=")
		self.assertEqual(payload["hub_endpoint"], "203.0.113.1:51820")
		self.assertEqual(payload["tunnel_ip"], "10.88.0.2")
		self.assertEqual(payload["tunnel_cidr"], "10.88.0.0/16")
		self.assertEqual(payload["atlas_id"], instance.atlas_id)
		self.assertTrue(payload["service_api_key"])
		self.assertTrue(payload["service_api_secret"])

		# hub-peer-add ran with the returned key + the /32 + the endpoint.
		add_call = run_host_task.call_args
		self.assertEqual(add_call.kwargs["script"], "hub-peer-add.py")
		self.assertEqual(add_call.kwargs["variables"]["PEER_PUBLIC_KEY"], "SPOKEPUBKEY=")
		self.assertEqual(add_call.kwargs["variables"]["ALLOWED_IPS"], "10.88.0.2/32")
		self.assertEqual(add_call.kwargs["variables"]["ENDPOINT"], "blr.atlas.example.test:51820")

		# verify ping went over the tunnel_url; confirm too.
		admin_ping.assert_any_call("https://10.88.0.2")
		confirm_tunnel.assert_called_once_with("https://10.88.0.2")

	def test_register_creates_scoped_service_user(self) -> None:
		instance = self.make_instance("blr-svc")
		ping, provision, confirm, host_task = self._patched()
		with ping, provision, confirm, host_task:
			register_atlas(instance)

		instance.reload()
		expected = f"atlas-blr-svc@{frappe.local.site}"
		self.assertEqual(instance.service_user, expected)
		user = frappe.get_doc("User", expected)
		roles = {row.role for row in user.roles}
		self.assertIn(SERVICE_ROLE, roles)
		self.assertNotIn("System Manager", roles)
		# The pushed creds are the ones stored on the service user.
		self.assertTrue(user.api_key)
		self.assertTrue(user.get_password("api_secret"))

	def test_allocates_next_free_ip(self) -> None:
		# An instance already holding .2 forces the next registration to .3.
		self.make_instance("blr-taken", tunnel_ip="10.88.0.2")
		instance = self.make_instance("fra-next")
		ping, provision, confirm, host_task = self._patched()
		with ping, provision, confirm, host_task:
			register_atlas(instance)
		instance.reload()
		self.assertEqual(instance.tunnel_ip, "10.88.0.3")

	def _register(self, region: str):
		"""Register an instance through the mocked happy path and return it Active."""
		instance = self.make_instance(region)
		ping, provision, confirm, host_task = self._patched()
		with ping, provision, confirm, host_task:
			register_atlas(instance)
		instance.reload()
		return instance

	# ----- remove_tunnel (strips the tunnel, KEEPS registration) -----------

	def test_remove_tunnel_strips_tunnel_but_stays_registered(self) -> None:
		instance = self._register("blr-remove")
		peer_key = instance.peer_public_key
		service_user = instance.service_user
		tunnel_url = instance.tunnel_url  # the deprovision target; capture before the call
		self.assertTrue(frappe.db.exists("User", service_user))

		deprov = patch.object(AtlasClient, "deprovision_tunnel", return_value={"tunnel_status": "Inactive"})
		host_task = patch("central.integrations.atlas.run_host_task", return_value=MagicMock())
		with deprov as deprovision_tunnel, host_task as run_host_task:
			out = remove_tunnel(instance)

		self.assertEqual(out["tunnel_status"], "Inactive")
		# Atlas teardown driven over the tunnel_url.
		deprovision_tunnel.assert_called_once_with(tunnel_url)
		# hub peer removed with the Atlas's key.
		remove_call = run_host_task.call_args
		self.assertEqual(remove_call.kwargs["script"], "hub-peer-remove.py")
		self.assertEqual(remove_call.kwargs["variables"]["PEER_PUBLIC_KEY"], peer_key)

		instance.reload()
		# tunnel runtime is gone...
		self.assertEqual(instance.tunnel_status, "Inactive")
		self.assertFalse(instance.peer_public_key)
		self.assertFalse(instance.peer_endpoint)
		# ...but the registration identity is RETAINED.
		self.assertTrue(instance.atlas_id)
		self.assertEqual(instance.service_user, service_user)
		self.assertEqual(instance.tunnel_ip, "10.88.0.2")
		self.assertTrue(frappe.db.exists("User", service_user))

	def test_remove_tunnel_tolerates_dropped_connection(self) -> None:
		instance = self._register("blr-remove-drop")
		# Atlas drops wg0 mid-call (the deprovision response never returns); cleanup
		# must still complete after re-verifying over the public base_url.
		deprov = patch.object(AtlasClient, "deprovision_tunnel", side_effect=ConnectionError("tunnel gone"))
		ping = patch.object(AtlasClient, "admin_ping", return_value={"message": "pong"})
		host_task = patch("central.integrations.atlas.run_host_task", return_value=MagicMock())
		with deprov, ping as admin_ping, host_task:
			out = remove_tunnel(instance)

		self.assertEqual(out["tunnel_status"], "Inactive")
		admin_ping.assert_called_once_with(instance.base_url)
		instance.reload()
		self.assertEqual(instance.tunnel_status, "Inactive")
		# still registered after a messy teardown.
		self.assertTrue(instance.service_user)

	def test_re_register_after_remove_reuses_identity(self) -> None:
		instance = self._register("blr-retunnel")
		atlas_id, service_user, tunnel_ip = instance.atlas_id, instance.service_user, instance.tunnel_ip
		# strip the tunnel (Inactive, still registered)
		with patch.object(AtlasClient, "deprovision_tunnel", return_value={}), patch(
			"central.integrations.atlas.run_host_task", return_value=MagicMock()
		):
			remove_tunnel(instance)
		instance.reload()
		self.assertEqual(instance.tunnel_status, "Inactive")
		# Register again → re-tunnels, reusing the same identity + address.
		ping, provision, confirm, host_task = self._patched()
		with ping, provision, confirm, host_task:
			register_atlas(instance)
		instance.reload()
		self.assertEqual(instance.tunnel_status, "Active")
		self.assertEqual(instance.atlas_id, atlas_id)
		self.assertEqual(instance.service_user, service_user)
		self.assertEqual(instance.tunnel_ip, tunnel_ip)

	def test_remove_tunnel_requires_system_manager(self) -> None:
		instance = self._register("blr-remove-perm")
		frappe.set_user(_make_plain_user())
		with self.assertRaises(frappe.PermissionError):
			remove_tunnel(instance)

	# ----- guards ----------------------------------------------------------

	def test_requires_hub_initialized(self) -> None:
		_set_hub(active=False)
		instance = self.make_instance("blr-nohub")
		with self.assertRaises(TunnelRegistrationError):
			register_atlas(instance)

	def test_requires_admin_creds(self) -> None:
		instance = self.make_instance("blr-nocreds")
		instance.db_set("api_key", None)
		with self.assertRaises(TunnelRegistrationError):
			register_atlas(instance)

	def test_requires_system_manager(self) -> None:
		instance = self.make_instance("blr-perm")
		frappe.set_user(_make_plain_user())
		with self.assertRaises(frappe.PermissionError):
			register_atlas(instance)

	# ----- rollback --------------------------------------------------------

	def test_rollback_when_provision_fails(self) -> None:
		instance = self.make_instance("blr-provfail")
		ping = patch.object(AtlasClient, "admin_ping", return_value={"message": "pong"})
		provision = patch.object(AtlasClient, "provision_tunnel", side_effect=RuntimeError("atlas down"))
		host_task = patch("central.integrations.atlas.run_host_task", return_value=MagicMock())
		with ping, provision, host_task as run_host_task:
			with self.assertRaises(TunnelRegistrationError):
				register_atlas(instance)

		instance.reload()
		self.assertEqual(instance.tunnel_status, "Unregistered")
		self.assertFalse(instance.service_user)
		# Peer was never added, so no hub-peer-remove either.
		run_host_task.assert_not_called()
		# The scoped service user was cleaned up.
		self.assertFalse(frappe.db.exists("User", f"atlas-blr-provfail@{frappe.local.site}"))

	def test_rollback_when_confirm_fails_removes_peer(self) -> None:
		instance = self.make_instance("blr-confirmfail")
		ping = patch.object(AtlasClient, "admin_ping", return_value={"message": "pong"})
		provision = patch.object(AtlasClient, "provision_tunnel", return_value=dict(PROVISION_RETURN))
		confirm = patch.object(AtlasClient, "confirm_tunnel", side_effect=RuntimeError("tunnel dead"))
		host_task = patch("central.integrations.atlas.run_host_task", return_value=MagicMock())
		with ping, provision, confirm, host_task as run_host_task:
			with self.assertRaises(TunnelRegistrationError):
				register_atlas(instance)

		instance.reload()
		self.assertEqual(instance.tunnel_status, "Unregistered")
		self.assertFalse(instance.service_user)
		scripts = [call.kwargs["script"] for call in run_host_task.call_args_list]
		self.assertIn("hub-peer-add.py", scripts)
		self.assertIn("hub-peer-remove.py", scripts)
		self.assertFalse(frappe.db.exists("User", f"atlas-blr-confirmfail@{frappe.local.site}"))
