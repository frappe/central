from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.servers import set_server_ipv4_internet, set_server_public_ip, set_server_wireguard_access
from central.billing.catalog.taxonomy_setup import ensure_catalog_masters
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

ADDRESS = "203.0.113.10"


class PublicIPTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "sync_subscription_on_status_change"))
		ensure_catalog_masters()

		self.developer = ensure_user("public-ip.developer@example.test")
		self.viewer = ensure_user("public-ip.viewer@example.test")
		members = [
			{"user": self.developer, "role": "Developer", "status": "Active"},
			{"user": self.viewer, "role": "Viewer", "status": "Active"},
		]
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Public IP",
					"owner_user": "Administrator",
					"members": members,
				}
			)
			.insert()
			.name
		)
		self.region = ensure_atlas_instance("test-public-ip")
		self.server = (
			frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": "public-ip-" + frappe.generate_hash(length=8),
					"team": self.team,
					"atlas_vm_id": "vm-public-ip",
					"region": self.region,
					"status": "Running",
				}
			)
			.insert()
			.name
		)


class TestPublicIPActions(PublicIPTestCase):
	def setUp(self):
		super().setUp()
		self.client = self.enterContext(patch("central.integrations.servers.get_client")).return_value
		self.client.get_vm.return_value = {"network": {"public_ipv4": ADDRESS}}
		self.enterContext(patch("central.integrations.servers.observe_server"))

	def test_attaching_ipv4_turns_on_internet_access_first(self):
		frappe.set_user(self.developer)

		result = set_server_public_ip(self.team, self.server, version=4, is_attached=1)

		self.assertEqual(result, {"is_pending": False})
		self.client.update_network.assert_called_once_with("vm-public-ip", {"ipv4_internet_access": True})
		self.client.attach_public_ip.assert_called_once_with("vm-public-ip", 4)

	def test_a_region_without_a_price_attaches_no_ipv4(self):
		frappe.set_user(self.developer)
		with (
			patch("central.billing.catalog.public_ips.get_public_ipv4_rates", return_value=[]),
			self.assertRaises(frappe.ValidationError),
		):
			set_server_public_ip(self.team, self.server, version=4, is_attached=1)

		self.client.attach_public_ip.assert_not_called()

	def test_a_viewer_cannot_attach_an_address(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_server_public_ip(self.team, self.server, version=6, is_attached=1)

		self.client.attach_public_ip.assert_not_called()

	def test_internet_access_stays_on_while_an_ipv4_is_attached(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", ADDRESS)
		frappe.set_user(self.developer)

		with self.assertRaises(frappe.ValidationError):
			set_server_ipv4_internet(self.team, self.server, enabled=0)

		self.client.update_network.assert_not_called()

	def test_wireguard_access_reaches_atlas_and_a_viewer_cannot_change_it(self):
		frappe.db.set_value("Region", self.region, "has_wireguard_gateway", 1)
		frappe.set_user(self.developer)
		set_server_wireguard_access(self.team, self.server, enabled=1)
		self.client.update_network.assert_called_once_with("vm-public-ip", {"wireguard_gateway_access": True})

		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			set_server_wireguard_access(self.team, self.server, enabled=0)

	def test_a_region_without_a_gateway_turns_on_no_wireguard_access(self):
		frappe.db.set_value("Region", self.region, "has_wireguard_gateway", 0)
		frappe.set_user(self.developer)

		with self.assertRaises(frappe.ValidationError):
			set_server_wireguard_access(self.team, self.server, enabled=1)

		self.client.update_network.assert_not_called()
