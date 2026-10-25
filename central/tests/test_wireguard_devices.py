from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.wireguard_device.wireguard_device import (
	remove_pending_devices,
	restore_devices,
)
from central.integrations.wireguard import WireGuardGatewayClient, WireGuardGatewayError
from central.permissions import wireguard_device_has_permission, wireguard_device_query_conditions
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

REGION = "wg-test"
PUBLIC_KEY = "HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw="
OTHER_KEY = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="


def settings(client_id: int) -> dict:
	return {
		"tenant_id": 1,
		"client_id": client_id,
		"address": f"fdac:1:2:0:2a::{client_id}/128",
		"allowed_ips": ["fdaa:1:0:2a::/64"],
		"endpoint": "wireguard-002.wg-test.example.com:51820",
		"public_key": "node-key",
	}


class TestWireGuardDevices(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		ensure_atlas_instance(REGION, has_wireguard_gateway=1)
		frappe.db.delete("WireGuard Device", {"region": REGION})
		self.owner = ensure_user("wg-owner@example.com")
		self.member = ensure_user("wg-member@example.com")
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": f"wg-{frappe.generate_hash(length=6)}",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.member, "role": "Developer", "status": "Active"},
				],
			}
		).insert()
		self.gateway = MagicMock()
		self.gateway.register_peer.side_effect = lambda tenant, client, key: settings(client)
		patcher = patch(
			"central.infrastructure.doctype.wireguard_device.wireguard_device.Region.get_wireguard_client",
			return_value=self.gateway,
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def add_device(self, user: str, public_key: str = PUBLIC_KEY):
		frappe.set_user(user)
		device = frappe.get_doc(
			{
				"doctype": "WireGuard Device",
				"team": self.team.name,
				"region": REGION,
				"title": "laptop",
				"public_key": public_key,
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		return device

	def test_new_devices_register_with_the_next_client_id(self) -> None:
		first = self.add_device(self.owner)
		second = self.add_device(self.member, OTHER_KEY)

		self.assertEqual((first.client_id, second.client_id), (1, 2))
		self.assertEqual(second.added_by, self.member)
		self.assertEqual(second.address, "fdac:1:2:0:2a::2/128")
		self.gateway.register_peer.assert_called_with(self.team.tenant_id, 2, OTHER_KEY)

	def test_a_bad_public_key_is_refused(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self.add_device(self.owner, "not-a-key")

	def test_gateway_outage_leaves_the_device_removing_until_a_retry_works(self) -> None:
		device = self.add_device(self.owner)
		self.gateway.remove_peer.side_effect = WireGuardGatewayError("down")

		self.assertFalse(device.remove())
		self.assertEqual(frappe.db.get_value("WireGuard Device", device.name, "status"), "Removing")

		self.gateway.remove_peer.side_effect = None
		remove_pending_devices()
		self.assertFalse(frappe.db.exists("WireGuard Device", device.name))

	@patch("central.infrastructure.doctype.wireguard_device.wireguard_device.frappe.enqueue")
	def test_a_member_who_leaves_loses_their_devices(self, enqueue) -> None:
		kept = self.add_device(self.owner)
		gone = self.add_device(self.member, OTHER_KEY)

		self.team.reload()
		self.team.remove(next(row for row in self.team.members if row.user == self.member))
		self.team.save()

		self.assertEqual(frappe.db.get_value("WireGuard Device", kept.name, "status"), "Active")
		self.assertEqual(frappe.db.get_value("WireGuard Device", gone.name, "status"), "Removing")
		enqueue.assert_called_once()

	def test_restore_keeps_each_device_on_its_node(self) -> None:
		device = self.add_device(self.owner)
		listed = {**settings(1), "tenant_id": self.team.tenant_id, "node_id": "wireguard-002"}
		self.gateway.list_peers.return_value = [{**listed, "endpoint": "wireguard-003:51820"}]

		self.assertEqual(restore_devices(REGION), 1)

		peers = self.gateway.replace_peers.call_args.args[0]
		self.assertEqual(peers[0]["node_id"], "wireguard-002")
		self.assertEqual(peers[0]["client_id"], device.client_id)
		self.assertEqual(
			frappe.db.get_value("WireGuard Device", device.name, "endpoint"), "wireguard-003:51820"
		)


class TestWireGuardAccess(IntegrationTestCase):
	@patch("central.permissions.user_has_operator_bypass", return_value=False)
	@patch("central.permissions.can_on_any_server")
	@patch("central.permissions.can")
	def test_viewers_read_and_only_wireguard_managers_write(self, can, on_any_server, _operator) -> None:
		on_any_server.side_effect = lambda user, team, capability: (
			team == "team-a" and capability == "server:view"
		)
		can.side_effect = lambda user, team, capability: (
			user == "manager" and capability == "server:wireguard"
		)
		doc = SimpleNamespace(team="team-a")

		self.assertTrue(wireguard_device_has_permission(doc, "viewer", "read"))
		self.assertFalse(wireguard_device_has_permission(doc, "viewer", "delete"))
		self.assertTrue(wireguard_device_has_permission(doc, "manager", "delete"))
		self.assertFalse(wireguard_device_has_permission(SimpleNamespace(team="team-b"), "viewer", "read"))

	@patch("central.permissions.user_has_operator_bypass", return_value=False)
	@patch("central.permissions.get_user_team_names_with_capability", return_value=[])
	def test_list_is_empty_without_server_view(self, _teams, _operator) -> None:
		self.assertEqual(wireguard_device_query_conditions("outsider"), "1 = 0")

	@patch("central.integrations.wireguard.register_peer.sync_detailed")
	def test_register_retries_once_and_names_a_key_in_use(self, register) -> None:
		client = WireGuardGatewayClient("https://wireguard.wg-test.example.com", "token")
		register.side_effect = [SimpleNamespace(status_code=503), SimpleNamespace(status_code=409)]

		with self.assertRaisesRegex(WireGuardGatewayError, "already used by another device"):
			client.register_peer(1, 1, PUBLIC_KEY)
		self.assertEqual(register.call_count, 2)
