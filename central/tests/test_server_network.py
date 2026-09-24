from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from central.integrations.server_provisioning import MESH_NETWORK, _create_payload


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
