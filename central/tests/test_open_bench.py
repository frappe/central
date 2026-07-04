from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.sso import get_bench_link
from central.tests.test_iam import ensure_user

# Open-in-bench for a real VM (asset) now hands back Atlas's one-click login URL —
# the scoped admin session minted in the guest — not a Central-signed SSO assertion.
# A stored URL that's still good is returned verbatim (no Atlas round-trip); an
# expired one is regenerated on the click. The legacy SSO-assertion path survives
# only for the explicit `gateway_url` dev shortcut (covered by test_sso.py).

FUTURE = "2099-01-01 00:00:00"
PAST = "2000-01-01 00:00:00"
STORED_URL = "https://vm-open-1.blr1.frappe.dev/app?sid=stored"


class TestOpenBench(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("open.owner@example.test")
		self.dev = ensure_user("open.dev@example.test")
		self.viewer = ensure_user("open.viewer@example.test")
		self.team = self._team()
		self.cluster = self._cluster("blr-open")
		self.asset = self._asset("vm-open-1", "Running", login_url=STORED_URL, expires_at=FUTURE)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _team(self):
		name = "Open Bench Team"
		existing = frappe.db.get_value("Team", {"team_name": name})
		if existing:
			frappe.delete_doc("Team", existing, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": name,
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.dev, "role": "Developer", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()

	def _cluster(self, region):
		if frappe.db.exists("Atlas Instance", region):
			frappe.delete_doc("Atlas Instance", region, force=True)
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": "https://atlas.example.test",
				"status": "Active",
				"api_key": "k",
				"api_secret": "s",
			}
		).insert()
		return region

	def _asset(self, rid, status, *, login_url="", expires_at=None, gateway="https://vm-open-1.blr1.frappe.dev"):
		if frappe.db.exists("Asset", rid):
			frappe.delete_doc("Asset", rid, force=True, ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": rid,
				"team": self.team.name,
				"cluster": self.cluster,
				"status": status,
				"gateway_url": gateway or None,
				"login_url": login_url or None,
				"login_url_expires_at": expires_at,
			}
		).insert(ignore_permissions=True)

	def _as(self, user, fn):
		frappe.set_user(user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	def test_open_running_vm_returns_its_login_url(self):
		"""A still-valid stored login URL is handed back verbatim — no Atlas round-trip."""
		with patch("central.integrations.atlas.AtlasClient.regenerate_vm_login") as regen:
			link = self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
		self.assertEqual(link["url"], STORED_URL)
		regen.assert_not_called()

	def test_expired_login_url_is_regenerated(self):
		"""An expired stored URL triggers a re-mint via Atlas, and the fresh URL is
		returned (and mirrored back onto the Asset)."""
		self._asset("vm-open-1", "Running", login_url=STORED_URL, expires_at=PAST)
		fresh_url = "https://vm-open-1.blr1.frappe.dev/app?sid=fresh"
		fresh_payload = {
			"name": "vm-open-1",
			"team": self.team.name,
			"status": "Running",
			"gateway_url": "https://vm-open-1.blr1.frappe.dev",
			"login_url": fresh_url,
			"login_url_expires_at": FUTURE,
		}
		with patch(
			"central.integrations.atlas.AtlasClient.regenerate_vm_login", return_value=fresh_payload
		) as regen:
			link = self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
		regen.assert_called_once_with("vm-open-1")
		self.assertEqual(link["url"], fresh_url)
		self.assertEqual(frappe.db.get_value("Asset", "vm-open-1", "login_url"), fresh_url)

	def test_regenerate_failure_falls_back_to_stored_url(self):
		"""If Atlas is unreachable when regenerating, Open falls back to the stored URL
		rather than blocking — a possibly-dead link is no worse than no link."""
		self._asset("vm-open-1", "Running", login_url=STORED_URL, expires_at=PAST)
		with patch(
			"central.integrations.atlas.AtlasClient.regenerate_vm_login", side_effect=Exception("down")
		):
			link = self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
		self.assertEqual(link["url"], STORED_URL)

	def test_viewer_without_vm_open_is_blocked(self):
		with self.assertRaises(frappe.PermissionError):
			self._as(self.viewer, lambda: get_bench_link(asset="vm-open-1"))

	def test_stopped_vm_refused(self):
		self._asset("vm-open-1", "Stopped", login_url=STORED_URL, expires_at=FUTURE)
		with self.assertRaises(frappe.ValidationError):
			self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))

	def test_missing_login_url_is_regenerated(self):
		"""An empty mirror login_url (the push that carries it lagged behind the reconcile)
		is re-minted via Atlas rather than refused — Open shouldn't block on mirror lag."""
		self._asset("vm-open-1", "Running", login_url="", expires_at=None)
		fresh_url = "https://vm-open-1.blr1.frappe.dev/app?sid=minted"
		fresh_payload = {
			"name": "vm-open-1",
			"team": self.team.name,
			"status": "Running",
			"gateway_url": "https://vm-open-1.blr1.frappe.dev",
			"login_url": fresh_url,
			"login_url_expires_at": FUTURE,
		}
		with patch(
			"central.integrations.atlas.AtlasClient.regenerate_vm_login", return_value=fresh_payload
		) as regen:
			link = self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
		regen.assert_called_once_with("vm-open-1")
		self.assertEqual(link["url"], fresh_url)
		self.assertEqual(frappe.db.get_value("Asset", "vm-open-1", "login_url"), fresh_url)

	def test_missing_login_url_and_atlas_down_refused(self):
		"""Empty mirror URL AND Atlas unreachable: there's no live link to hand back, so
		Open is refused with a clear message rather than opening a dead/empty URL."""
		self._asset("vm-open-1", "Running", login_url="", expires_at=None)
		with patch(
			"central.integrations.atlas.AtlasClient.regenerate_vm_login", side_effect=Exception("down")
		):
			with self.assertRaises(frappe.ValidationError):
				self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))

	def test_disabled_cluster_refused(self):
		frappe.db.set_value("Atlas Instance", self.cluster, "status", "Disabled")
		with self.assertRaises(frappe.ValidationError):
			self._as(self.dev, lambda: get_bench_link(asset="vm-open-1"))
