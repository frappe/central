import json
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from pydantic import ValidationError

from central.api.servers import update_server_firewall
from central.errors import AtlasRejected
from central.infrastructure.doctype.virtual_machine.firewall import (
	ANYWHERE,
	LEGACY_DEVICE_RULE,
	PRIVATE_NETWORK,
	get_atlas_firewall,
	get_customer_rules,
	get_observed_firewall,
	is_blocking_devices,
)
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.servers import remove_legacy_device_rule
from central.server_models import FirewallChange, FirewallRule
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

SSH = {"protocol": "tcp", "ports": "22", "cidrs": ANYWHERE}
PRIVATE = {"protocol": "any", "ports": "", "cidrs": [PRIVATE_NETWORK]}
ALL_OUT = {"protocol": "any", "ports": "", "cidrs": ANYWHERE}


class TestFirewallRules(TestCase):
	def test_a_rule_refuses_ports_it_cannot_use(self) -> None:
		for rule in (
			{"protocol": "icmp", "ports": "22", "cidrs": ANYWHERE},
			{"protocol": "tcp", "ports": "22-21", "cidrs": ANYWHERE},
			{"protocol": "tcp", "ports": "70000", "cidrs": ANYWHERE},
			{"protocol": "tcp", "ports": "022", "cidrs": ANYWHERE},
		):
			with self.subTest(rule=rule), self.assertRaises(ValidationError):
				FirewallRule.model_validate(rule)

	def test_a_rule_needs_canonical_address_ranges(self) -> None:
		for cidr in ("198.51.100.7", "198.51.100.1/24", "not-an-address"):
			with self.subTest(cidr=cidr), self.assertRaises(ValidationError):
				FirewallRule.model_validate({"protocol": "tcp", "ports": "22", "cidrs": [cidr]})

		FirewallRule.model_validate({"protocol": "tcp", "ports": "8000-8100", "cidrs": ["198.51.100.0/24"]})

	def test_a_rule_appears_only_once(self) -> None:
		with self.assertRaises(ValidationError):
			FirewallChange.model_validate({"enabled": True, "inbound": [SSH, SSH]})

	def test_atlas_gets_exactly_the_customer_rules(self) -> None:
		remote = get_atlas_firewall(
			FirewallChange.model_validate({"enabled": False, "inbound": [SSH], "outbound": [ALL_OUT]})
		)

		self.assertFalse(remote["enabled"])
		self.assertEqual(remote["inbound"], [SSH])
		self.assertEqual(remote["outbound"], [ALL_OUT])

	def test_a_change_sends_only_its_own_fields(self) -> None:
		self.assertEqual(
			get_atlas_firewall(FirewallChange.model_validate({"enabled": False})), {"enabled": False}
		)

		with self.assertRaises(ValidationError):
			FirewallChange.model_validate({})

	def test_the_customer_sees_every_rule_including_the_defaults(self) -> None:
		remote = {
			"inbound": [PRIVATE, LEGACY_DEVICE_RULE, {"protocol": "tcp", "ports": "22", "cidrs": ANYWHERE}]
		}

		self.assertEqual(
			get_customer_rules(remote), {"inbound": [PRIVATE, LEGACY_DEVICE_RULE, SSH], "outbound": []}
		)

	def test_the_report_fills_the_stored_fields(self) -> None:
		network = {"firewall": {"enabled": True, "inbound": [PRIVATE, SSH]}}

		state = get_observed_firewall(network)

		self.assertEqual(state["is_firewall_enabled"], True)
		self.assertEqual(json.loads(state["firewall_rules"]), {"inbound": [PRIVATE, SSH], "outbound": []})

	def test_an_enabled_firewall_blocks_devices_until_a_rule_names_them(self) -> None:
		device = {"protocol": "tcp", "ports": "22", "cidrs": ["fdac:1:2:0:2a::1/128"]}
		ping = {"protocol": "icmp", "ports": "", "cidrs": ANYWHERE}

		self.assertTrue(is_blocking_devices(True, [PRIVATE, ping]))
		self.assertFalse(is_blocking_devices(True, [PRIVATE, device]))
		self.assertFalse(is_blocking_devices(True, [SSH]))
		self.assertFalse(is_blocking_devices(False, []))


class TestServerFirewall(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "sync_subscription_on_status_change"))

		self.developer = ensure_user("network.developer@example.test")
		self.viewer = ensure_user("network.viewer@example.test")
		members = [
			{"user": self.developer, "role": "Developer", "status": "Active"},
			{"user": self.viewer, "role": "Viewer", "status": "Active"},
		]
		self.team = (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": "Network A",
					"owner_user": "Administrator",
					"members": members,
				}
			)
			.insert()
			.name
		)
		region = ensure_atlas_instance("test-network")
		self.first = self._server(region, "vm-first")
		self.second = self._server(region, "vm-second")
		self.client = self.enterContext(patch("central.integrations.servers.get_client")).return_value
		self.observe = self.enterContext(patch("central.integrations.servers.observe_server"))

	def _server(self, region: str, atlas_vm_id: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": "network-" + frappe.generate_hash(length=8),
					"team": self.team,
					"atlas_vm_id": atlas_vm_id,
					"region": region,
					"status": "Running",
				}
			)
			.insert()
			.name
		)

	def test_the_firewall_is_sent_as_is_then_read_back(self):
		frappe.set_user(self.developer)
		firewall = {"enabled": True, "inbound": [SSH], "outbound": [ALL_OUT]}

		result = update_server_firewall(self.team, [self.first], firewall=firewall)

		self.assertEqual(result, {self.first: None})
		self.client.update_network.assert_called_once_with(
			"vm-first",
			{"firewall": {"enabled": True, "inbound": [SSH], "outbound": [ALL_OUT]}},
		)
		self.observe.assert_called_once()

	def test_copying_reports_each_server(self):
		self.client.update_network.side_effect = [None, AtlasRejected("Atlas refused the firewall.")]
		frappe.set_user(self.developer)

		result = update_server_firewall(
			self.team, [self.first, self.second], firewall={"enabled": True, "inbound": [SSH]}
		)

		self.assertEqual(result, {self.first: None, self.second: "Atlas refused the firewall."})

	def test_turning_the_firewall_off_keeps_its_rules(self):
		frappe.set_user(self.developer)
		update_server_firewall(self.team, [self.first], firewall={"enabled": False})

		self.client.update_network.assert_called_once_with("vm-first", {"firewall": {"enabled": False}})

	def test_a_viewer_cannot_change_the_network(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			update_server_firewall(self.team, [self.first], firewall={"enabled": True})

		self.client.update_network.assert_not_called()

	def test_an_invalid_firewall_reaches_no_server(self):
		frappe.set_user(self.developer)
		with self.assertRaises(frappe.ValidationError):
			update_server_firewall(self.team, [self.first], firewall={"enabled": True, "inbound": [SSH, SSH]})

		self.client.update_network.assert_not_called()

	def test_a_terminated_server_is_left_alone(self):
		frappe.db.set_value("Virtual Machine", self.first, "status", "Terminated")
		frappe.set_user(self.developer)

		result = update_server_firewall(self.team, [self.first], firewall={"enabled": True})

		self.assertEqual(result, {self.first: "This server is terminated."})
		self.client.update_network.assert_not_called()

	def test_the_legacy_device_rule_is_removed_and_the_rest_kept(self):
		rules = {"inbound": [PRIVATE, LEGACY_DEVICE_RULE, SSH], "outbound": [ALL_OUT]}
		frappe.db.set_value("Virtual Machine", self.first, "firewall_rules", json.dumps(rules))

		remove_legacy_device_rule(frappe.get_doc("Virtual Machine", self.first))

		self.client.update_network.assert_called_once_with(
			"vm-first", {"firewall": {"inbound": [PRIVATE, SSH]}}
		)

	def test_a_server_without_the_legacy_rule_is_left_alone(self):
		rules = {"inbound": [SSH], "outbound": [ALL_OUT]}
		frappe.db.set_value("Virtual Machine", self.first, "firewall_rules", json.dumps(rules))

		remove_legacy_device_rule(frappe.get_doc("Virtual Machine", self.first))

		self.client.update_network.assert_not_called()
