import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.firewall_rulesets import (
	delete_firewall_ruleset,
	list_firewall_rulesets,
	save_firewall_ruleset,
	set_server_firewall_rulesets,
)
from central.api.servers import update_server_firewall
from central.errors import AtlasRejected
from central.infrastructure.doctype.firewall_ruleset.firewall_ruleset import FirewallRuleset
from central.infrastructure.doctype.virtual_machine.firewall import ANYWHERE
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.tests.test_iam import ensure_user
from central.tests.utils import ensure_atlas_instance

SSH = {"protocol": "tcp", "ports": "22", "cidrs": ANYWHERE}
HTTPS = {"protocol": "tcp", "ports": "443", "cidrs": ANYWHERE}
RULES = {"inbound": [SSH], "outbound": []}


class TestFirewallRulesets(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.enterContext(patch.object(VirtualMachine, "sync_subscription_on_status_change"))
		self.developer = ensure_user("ruleset-developer@example.com")
		self.viewer = ensure_user("ruleset-viewer@example.com")
		self.outsider = ensure_user("ruleset-outsider@example.com")
		self.team = self._team("Ruleset A", [(self.developer, "Developer"), (self.viewer, "Viewer")])
		self.other_team = self._team("Ruleset B", [(self.outsider, "Developer")])
		region = ensure_atlas_instance("test-ruleset")
		self.first = self._server(region, "vm-first")
		self.second = self._server(region, "vm-second")
		self.client = self.enterContext(patch("central.integrations.servers.get_client")).return_value
		self.enterContext(patch("central.integrations.servers.observe_server"))
		frappe.set_user(self.developer)

	def _team(self, team_name: str, members: list[tuple[str, str]]) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Team",
					"team_name": team_name,
					"owner_user": "Administrator",
					"members": [{"user": user, "role": role, "status": "Active"} for user, role in members],
				}
			)
			.insert()
			.name
		)

	def _server(self, region: str, atlas_vm_id: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Virtual Machine",
					"resource_id": "ruleset-" + frappe.generate_hash(length=8),
					"team": self.team,
					"atlas_vm_id": atlas_vm_id,
					"region": region,
					"status": "Running",
				}
			)
			.insert()
			.name
		)

	def test_applying_rulesets_sends_their_rules_once_and_turns_the_firewall_on(self):
		base = save_firewall_ruleset(self.team, "Base", RULES)
		web = save_firewall_ruleset(self.team, "Web", {"inbound": [SSH, HTTPS], "outbound": []})

		set_server_firewall_rulesets(self.team, self.first, [base, web])

		self.client.update_network.assert_called_once_with(
			"vm-first", {"firewall": {"enabled": True, "inbound": [SSH, HTTPS], "outbound": []}}
		)
		self.assertEqual(
			[row.firewall_ruleset for row in frappe.get_doc("Virtual Machine", self.first).firewall_rulesets],
			[base, web],
		)
		self.assertEqual([row["server_count"] for row in list_firewall_rulesets(self.team)], [1, 1])

	def test_rulesets_with_too_many_addresses_together_are_refused(self):
		ranges = [f"198.51.{number}.0/24" for number in range(26)]
		names = [
			save_firewall_ruleset(
				self.team,
				title,
				{"inbound": [{"protocol": "tcp", "ports": port, "cidrs": ranges}], "outbound": []},
			)
			for title, port in (("Office", "22"), ("Partners", "443"))
		]

		with self.assertRaises(frappe.ValidationError):
			set_server_firewall_rulesets(self.team, self.first, names)

		self.client.update_network.assert_not_called()

	def test_a_changed_ruleset_reaches_each_server_and_records_the_failed_one(self):
		base = save_firewall_ruleset(self.team, "Base", RULES)
		web = save_firewall_ruleset(self.team, "Web", RULES)
		set_server_firewall_rulesets(self.team, self.first, [base, web])
		set_server_firewall_rulesets(self.team, self.second, [web])
		self.client.update_network.reset_mock()
		self.client.update_network.side_effect = [None, AtlasRejected("Atlas refused the firewall.")]

		with patch.object(FirewallRuleset, "queue_sync", FirewallRuleset.sync):
			save_firewall_ruleset(self.team, "Web", {"inbound": [HTTPS], "outbound": []}, name=web)

		# The first server keeps the rule of its other ruleset.
		self.assertCountEqual(
			[call.args[1]["firewall"]["inbound"] for call in self.client.update_network.call_args_list],
			[[SSH, HTTPS], [HTTPS]],
		)
		error = frappe.db.get_value("Firewall Ruleset", web, "last_sync_error")
		self.assertEqual(sum(server in error for server in (self.first, self.second)), 1)

	def test_a_server_with_rulesets_refuses_its_own_rule_edits_until_detached(self):
		name = save_firewall_ruleset(self.team, "Web", RULES)
		set_server_firewall_rulesets(self.team, self.first, [name])

		result = update_server_firewall(self.team, [self.first], firewall={"inbound": [HTTPS]})
		self.assertIn("ruleset", result[self.first])

		set_server_firewall_rulesets(self.team, self.first, [])
		self.assertEqual(
			update_server_firewall(self.team, [self.first], firewall={"inbound": [HTTPS]}),
			{self.first: None},
		)

	def test_a_ruleset_in_use_cannot_be_deleted(self):
		name = save_firewall_ruleset(self.team, "Web", RULES)
		set_server_firewall_rulesets(self.team, self.first, [name])

		with self.assertRaises(frappe.ValidationError):
			delete_firewall_ruleset(self.team, name)

		set_server_firewall_rulesets(self.team, self.first, [])
		delete_firewall_ruleset(self.team, name)
		self.assertFalse(frappe.db.exists("Firewall Ruleset", name))

	def test_a_team_cannot_have_two_rulesets_with_one_name(self):
		save_firewall_ruleset(self.team, "Web", RULES)

		with self.assertRaises(frappe.ValidationError):
			save_firewall_ruleset(self.team, "Web", RULES)

	def test_a_viewer_reads_rulesets_but_cannot_change_them(self):
		name = save_firewall_ruleset(self.team, "Web", RULES)
		frappe.set_user(self.viewer)

		self.assertEqual([row["name"] for row in list_firewall_rulesets(self.team)], [name])
		self.assertEqual(json.loads(frappe.get_doc("Firewall Ruleset", name).rules), RULES)
		self.assertFalse(frappe.has_permission("Firewall Ruleset", "write", name))
		for change in (
			lambda: save_firewall_ruleset(self.team, "Web 2", RULES),
			lambda: delete_firewall_ruleset(self.team, name),
			lambda: set_server_firewall_rulesets(self.team, self.first, [name]),
		):
			with self.assertRaises(frappe.PermissionError):
				change()

	def test_another_team_cannot_see_or_use_a_ruleset(self):
		name = save_firewall_ruleset(self.team, "Web", RULES)
		frappe.set_user(self.outsider)

		self.assertEqual(frappe.get_list("Firewall Ruleset", pluck="name"), [])
		self.assertFalse(frappe.has_permission("Firewall Ruleset", "read", name))
		with self.assertRaises(frappe.PermissionError):
			list_firewall_rulesets(self.team)
		with self.assertRaises(frappe.PermissionError):
			save_firewall_ruleset(self.other_team, "Stolen", RULES, name=name)
