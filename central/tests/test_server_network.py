from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import open_console, server_overview
from central.integrations.server_provisioning import MESH_NETWORK, _create_payload
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

CONSOLE_URL = "https://atlas.example.test/vm_console#token=one-time"


def creation_request(purpose: str = "base", **options) -> SimpleNamespace:
	configuration = SimpleNamespace(
		image_id="ubuntu-image",
		virtual_cpu_count=2,
		memory_mib=2048,
		disk_mib=20480,
		hostname="worker",
		ssh_keys=["ssh-ed25519 AAAA"],
		ssh_key_ids=[],
		image_tags={"os": "Ubuntu", "purpose": purpose},
		has_public_ipv6=options.get("has_public_ipv6", False),
		is_firewall_enabled=options.get("is_firewall_enabled", False),
	)
	return SimpleNamespace(name="action-1", team="team-a", get_configuration=lambda: configuration)


@patch("central.integrations.server_provisioning.idle_shutdown_seconds", return_value=0)
class TestCreationNetworkPayload(TestCase):
	def test_no_public_address_and_open_firewall_by_default(self, _idle) -> None:
		payload = _create_payload(creation_request())

		self.assertNotIn("public_ipv4", payload)
		self.assertNotIn("public_ipv6", payload)
		self.assertEqual(payload["firewall"], {"enabled": False})

	def test_public_ipv6_asks_atlas_for_an_automatic_address(self, _idle) -> None:
		payload = _create_payload(creation_request(has_public_ipv6=True))

		self.assertEqual(payload["public_ipv6"], "auto")

	def test_firewall_keeps_the_mesh_and_web_ports_open(self, _idle) -> None:
		firewall = _create_payload(creation_request(is_firewall_enabled=True))["firewall"]

		self.assertTrue(firewall["enabled"])
		self.assertIn({"protocol": "any", "cidrs": [MESH_NETWORK]}, firewall["inbound"])
		self.assertIn({"protocol": "icmp", "cidrs": ["0.0.0.0/0", "::/0"]}, firewall["inbound"])
		self.assertEqual(
			[rule["ports"] for rule in firewall["inbound"] if rule["protocol"] == "tcp"],
			["22", "80", "443"],
		)
		self.assertEqual(firewall["outbound"], [{"protocol": "any", "cidrs": ["0.0.0.0/0", "::/0"]}])


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

	def open_as(self, user: str, team: str | None = None) -> dict:
		frappe.set_user(user)
		try:
			return open_console(team=team or self.team.name, resource_id=self.server.name)
		finally:
			frappe.set_user("Administrator")

	def test_owner_gets_a_single_use_ssh_console_url(self):
		self.assertEqual(self.open_as(self.owner), {"url": CONSOLE_URL})
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

	def test_console_needs_a_running_ubuntu_server(self):
		self.server.db_set("status", "Stopped")
		with self.assertRaises(frappe.ValidationError):
			self.open_as(self.owner)

		self.server.db_set({"status": "Running", "image_offering": "pilot"})
		with self.assertRaises(frappe.ValidationError):
			self.open_as(self.owner)
		self.get_console_url.assert_not_called()

	def test_overview_signs_in_over_public_ipv6_first(self):
		frappe.set_user(self.viewer)
		try:
			server = server_overview(team=self.team.name, resource_id=self.server.name)["server"]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(server["public_ipv6"], "2001:db8:5::7")
		self.assertEqual(server["ssh_command"], "ssh root@2001:db8:5::7")
