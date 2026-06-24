# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.central.doctype.central_tunnel_settings.central_tunnel_settings import next_free_ip


class IntegrationTestCentralTunnelSettings(IntegrationTestCase):
	def test_next_free_ip_skips_the_hub(self):
		# .1 is the hub; the first Atlas peer is .2.
		self.assertEqual(next_free_ip("10.88.0.0/16", set()), "10.88.0.2")

	def test_next_free_ip_skips_used(self):
		self.assertEqual(next_free_ip("10.88.0.0/16", {"10.88.0.2"}), "10.88.0.3")

	def test_next_free_ip_reuses_lowest_gap(self):
		# .2 free, .3 taken -> lowest free is .2 (a released peer returns to the pool).
		self.assertEqual(next_free_ip("10.88.0.0/16", {"10.88.0.3"}), "10.88.0.2")

	def test_next_free_ip_exhausted_raises(self):
		# /30 hosts are .1 (hub) and .2; with .2 used the pool is empty.
		with self.assertRaises(frappe.ValidationError):
			next_free_ip("10.0.0.0/30", {"10.0.0.2"})

	def test_hub_address_is_first_host_with_mask(self):
		settings = frappe.get_single("Central Tunnel Settings")
		settings.tunnel_cidr = "10.88.0.0/16"
		self.assertEqual(settings.hub_address(), "10.88.0.1/16")

	def test_allocate_tunnel_ip_starts_at_two(self):
		settings = frappe.get_single("Central Tunnel Settings")
		settings.tunnel_cidr = "10.88.0.0/16"
		self.assertEqual(settings.allocate_tunnel_ip(), "10.88.0.2")

	def test_initialize_hub_records_public_key_and_status(self):
		settings = frappe.get_single("Central Tunnel Settings")
		settings.hub_private_key_path = "/etc/wireguard/wg0.key"
		settings.tunnel_cidr = "10.88.0.0/16"
		settings.listen_port = 51820
		settings.hub_interface = "wg0"
		settings.save()

		fake_task = frappe._dict(
			name="HOSTTASK-TEST",
			stdout='trace line\nATLAS_RESULT={"public_key": "PUBKEY=", '
			'"address": "10.88.0.1/16", "listen_port": 51820, "interface": "wg0"}',
		)
		with patch("central.host_task.run_host_task", return_value=fake_task) as run:
			result = settings.initialize_hub()

		run.assert_called_once()
		_, kwargs = run.call_args
		self.assertEqual(kwargs["script"], "hub-up.py")
		self.assertEqual(kwargs["variables"]["ADDRESS"], "10.88.0.1/16")
		self.assertEqual(kwargs["variables"]["LISTEN_PORT"], 51820)

		self.assertEqual(result["public_key"], "PUBKEY=")
		settings.reload()
		self.assertEqual(settings.hub_public_key, "PUBKEY=")
		self.assertEqual(settings.hub_status, "Active")
