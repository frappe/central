from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import open_console, server_overview
from central.errors import AtlasConnectionError, AtlasRejected, AtlasResourceGone
from central.infrastructure.doctype.virtual_machine.firewall import SYSTEM_INBOUND_RULES
from central.integrations.resource_actions import _create_payload
from central.resource_actions import validate_guest_input
from central.server_models import MAXIMUM_USER_DATA_BYTES, CreateServerInput
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

CONSOLE_URL = "https://atlas.example.test/vm_console#token=one-time"


def creation_request(purpose: str = "base", **options) -> SimpleNamespace:
	configuration = SimpleNamespace(
		image_id="ubuntu-image",
		cpu_millicores=2000,
		memory_mib=2048,
		disk_mib=20480,
		hostname="worker",
		ssh_keys=["ssh-ed25519 AAAA"],
		ssh_key_ids=[],
		image_tags={"os": "Ubuntu", "purpose": purpose},
		has_public_ipv4=options.get("has_public_ipv4", False),
		has_public_ipv6=options.get("has_public_ipv6", False),
		is_firewall_enabled=options.get("is_firewall_enabled", False),
		user_data=options.get("user_data", ""),
	)
	return SimpleNamespace(name="action-1", team="team-a", get_configuration=lambda: configuration)


@patch("central.integrations.resource_actions.idle_shutdown_seconds", return_value=0)
class TestCreationNetworkPayload(TestCase):
	def test_no_public_address_and_open_firewall_by_default(self, _idle) -> None:
		payload = _create_payload(creation_request())

		self.assertNotIn("public_ipv4", payload)
		self.assertNotIn("public_ipv6", payload)
		self.assertFalse(payload["firewall"]["enabled"])

	def test_public_addresses_ask_atlas_for_automatic_addresses(self, _idle) -> None:
		payload = _create_payload(creation_request(has_public_ipv4=True, has_public_ipv6=True))

		self.assertEqual(payload["public_ipv4"], "auto")
		self.assertEqual(payload["public_ipv6"], "auto")

	def test_every_new_server_gets_the_web_server_rules(self, _idle) -> None:
		firewall = _create_payload(creation_request())["firewall"]

		self.assertEqual(firewall["inbound"][: len(SYSTEM_INBOUND_RULES)], SYSTEM_INBOUND_RULES)
		self.assertEqual(
			[rule["ports"] for rule in firewall["inbound"] if rule["protocol"] == "tcp"],
			["22", "80", "443"],
		)
		self.assertEqual(
			firewall["outbound"], [{"protocol": "any", "ports": "", "cidrs": ["0.0.0.0/0", "::/0"]}]
		)
		self.assertTrue(_create_payload(creation_request(is_firewall_enabled=True))["firewall"]["enabled"])

	def test_user_data_reaches_atlas(self, _idle) -> None:
		script = "#!/bin/sh\necho ready\n"

		self.assertEqual(_create_payload(creation_request())["user_data"], "")
		self.assertEqual(_create_payload(creation_request(user_data=script))["user_data"], script)

	def test_server_limits_come_from_central_settings(self, _idle) -> None:
		limits = {
			"disk_iops": 4000,
			"disk_throughput_mibps": 250,
			"private_network_throughput_mibps": 900,
			"public_network_throughput_mibps": 300,
		}
		settings = SimpleNamespace(**limits)

		with patch("frappe.get_cached_doc", return_value=settings):
			payload = _create_payload(creation_request())

		self.assertEqual({key: payload[key] for key in limits}, limits)


def guest_input(user_data: str) -> CreateServerInput:
	return CreateServerInput(
		team="team-a",
		region="region-a",
		title="Worker",
		offering="ubuntu",
		image_id="ubuntu-image",
		request_key="request-key-0000001",
		plan="plan-a",
		user_data=user_data,
	)


class TestGuestInput(TestCase):
	def test_user_data_keeps_its_whitespace(self) -> None:
		script = "#cloud-config\nruncmd: []\n"

		self.assertEqual(guest_input(script).user_data, script)

	def test_user_data_over_the_atlas_limit_is_refused(self) -> None:
		validate_guest_input(guest_input("#!/bin/sh\n" + "x" * 16_000))
		with self.assertRaises(frappe.ValidationError):
			validate_guest_input(guest_input("#!/bin/sh\n" + "x" * MAXIMUM_USER_DATA_BYTES))


class TestServerConsole(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = ensure_user("console.owner@example.test")
		self.viewer = ensure_user("console.viewer@example.test")
		self.outsider = ensure_user("console.outsider@example.test")
		self.team = self.create_team("Console Team", self.owner, viewer=self.viewer)
		self.other_team = self.create_team("Console Other Team", self.outsider)

		self.region = "blr-console"
		ensure_atlas_instance(self.region)
		self.server = frappe.get_doc(
			{
				"doctype": "Virtual Machine",
				"resource_id": f"vm-console-{frappe.generate_hash(length=8)}",
				"title": "Console server",
				"team": self.team.name,
				"region": self.region,
				"status": "Running",
				"image_offering": "ubuntu",
				"atlas_vm_id": "vm-00001",
				"public_ipv4": "203.0.113.10",
				"public_ipv6": "2001:db8:5::7",
			}
		).insert()
		self.addCleanup(self.server.delete, ignore_permissions=True, force=True)

		atlas = self.enterContext(patch("central.integrations.servers.AtlasClient"))
		self.get_console_url = atlas.return_value.get_console_url
		self.get_console_url.return_value = CONSOLE_URL

	def tearDown(self):
		frappe.set_user("Administrator")

	def create_team(self, name: str, owner: str, viewer: str | None = None):
		members = [{"user": owner, "role": "Owner", "status": "Active"}]
		if viewer:
			members.append({"user": viewer, "role": "Viewer", "status": "Active"})
		team = frappe.get_doc(
			{"doctype": "Team", "team_name": name, "owner_user": owner, "members": members}
		).insert()
		self.addCleanup(team.delete, ignore_permissions=True, force=True)
		return team

	def open_as(self, user: str, team: str | None = None, mode: str = "ssh") -> dict:
		frappe.set_user(user)
		try:
			return open_console(team=team or self.team.name, resource_id=self.server.name, mode=mode)
		finally:
			frappe.set_user("Administrator")

	def test_owner_gets_a_single_use_ssh_console_url(self):
		self.assertEqual(self.open_as(self.owner), {"url": CONSOLE_URL})
		self.get_console_url.assert_called_once_with("vm-00001", mode="ssh")

	def test_owner_gets_a_single_use_tty_console_url(self):
		self.assertEqual(self.open_as(self.owner, mode="tty"), {"url": CONSOLE_URL})
		self.get_console_url.assert_called_once_with("vm-00001", mode="tty")

	def test_refused_ssh_points_to_tty_without_switching_mode(self):
		self.get_console_url.side_effect = AtlasRejected("SSH is unavailable.")

		with self.assertRaisesRegex(frappe.ValidationError, "serial console"):
			self.open_as(self.owner)
		self.get_console_url.assert_called_once_with("vm-00001", mode="ssh")

	def test_refused_tty_reports_the_atlas_rejection(self):
		self.get_console_url.side_effect = AtlasRejected("The console is unavailable.")

		with self.assertRaises(frappe.ValidationError) as raised:
			self.open_as(self.owner, mode="tty")
		self.assertEqual(raised.exception.envelope["code"], "ATLAS_REJECTED")

	def test_console_rejects_an_unknown_mode(self):
		# Frappe's own type check refuses it first where it validates Literal annotations.
		with self.assertRaises((frappe.ValidationError, frappe.exceptions.FrappeTypeError)):
			self.open_as(self.owner, mode="vnc")
		self.get_console_url.assert_not_called()

	def test_console_reports_atlas_failures_as_they_are(self):
		for error, code in (
			(AtlasResourceGone("The server does not exist."), "RESOURCE_GONE"),
			(AtlasConnectionError("Atlas rejected Central authentication."), "REGION_UNAVAILABLE"),
		):
			with self.subTest(error=type(error).__name__):
				self.get_console_url.reset_mock()
				self.get_console_url.side_effect = error

				with self.assertRaises(frappe.ValidationError) as raised:
					self.open_as(self.owner)
				self.assertEqual(raised.exception.envelope["code"], code)
				self.get_console_url.assert_called_once_with("vm-00001", mode="ssh")

	def test_viewer_cannot_open_the_console(self):
		with self.assertRaises(frappe.PermissionError):
			self.open_as(self.viewer)
		self.get_console_url.assert_not_called()

	def test_another_team_cannot_open_the_console(self):
		with self.assertRaises(frappe.PermissionError):
			self.open_as(self.outsider)
		# The outsider's own Team holds the capability, but not this server.
		with self.assertRaises(frappe.DoesNotExistError):
			self.open_as(self.outsider, team=self.other_team.name)
		self.get_console_url.assert_not_called()

	def test_console_needs_a_running_server(self):
		self.server.db_set("status", "Stopped")
		with self.assertRaises(frappe.ValidationError):
			self.open_as(self.owner)
		self.get_console_url.assert_not_called()

	def test_pilot_server_opens_the_console(self):
		self.server.db_set("image_offering", "pilot")

		self.assertEqual(self.open_as(self.owner), {"url": CONSOLE_URL})

	def test_overview_signs_in_over_public_ipv6_first(self):
		frappe.set_user(self.viewer)
		try:
			server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(server["public_ipv6"], "2001:db8:5::7")
		self.assertEqual(server["ssh_command"], "ssh root@2001:db8:5::7")

	def test_overview_gives_an_operator_desk_and_atlas_links(self):
		links = server_overview(team=self.team.name, resource_id=self.server.name)["server"]["operator_links"]

		self.assertTrue(links["desk_url"].endswith(f"/desk/virtual-machine/{self.server.name}"))
		base_url = frappe.db.get_value("Region", self.region, "base_url").rstrip("/")
		self.assertEqual(links["atlas_url"], f"{base_url}/desk/virtual-machine/vm-00001")

	def test_overview_hides_operator_links_from_a_team_owner(self):
		frappe.set_user(self.owner)
		try:
			server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]
		finally:
			frappe.set_user("Administrator")

		self.assertIsNone(server["operator_links"])
