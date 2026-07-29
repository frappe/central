# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Staging trial teams provision servers on free welcome credits.

A team flagged `is_staging_trial` creates servers without a complete billing profile: it needs
only a billing currency, a plan (so usage meters against its credits), unspent credits,
and room under the `TRIAL_SERVER_LIMIT` cap. Size and price come from the chosen plan,
exactly as a normal create — the New Server form is what limits a trial to the entry
tiers. Non-trial teams are unaffected: they still need a complete profile."""

from unittest.mock import MagicMock, patch

import frappe

from central.api import servers
from central.billing.revenue import credits
from central.billing.tests.utils import (
	BillingTestCase as IntegrationTestCase,
)
from central.billing.tests.utils import (
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)

TEAM = "team-trial-provisioning"
REGION = "ap-south-1"
VM_ID = "vm-trial-test"


class TestTrialProvisioning(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(REGION)
		ensure_team(TEAM)
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		self._minimal_profile(TEAM, "INR")
		self.plan = make_plan("trial-starter", rates=[{"cluster": "", "currency": "INR", "rate": 500}])
		self._reset_team()
		frappe.set_user("Administrator")

	def _minimal_profile(self, team, currency):
		"""A currency-only Billing Profile — the state signup leaves a trial team in."""
		if frappe.db.exists("Billing Profile", team):
			frappe.db.set_value("Billing Profile", team, "currency", currency)
			return
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, "currency": currency})
		doc.insert(ignore_permissions=True, ignore_mandatory=True)

	def _reset_team(self):
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.db.delete("Asset", {"team": TEAM})

	def _fund(self, amount=2500):
		credits.grant_promotional_credits(TEAM, amount, "INR")

	def _seed_asset(self, resource_id, status="Running"):
		doc = frappe.get_doc(
			{"doctype": "Asset", "team": TEAM, "cluster": REGION, "title": resource_id, "status": status}
		)
		doc.flags.name_set = True
		doc.name = resource_id
		doc.insert(ignore_permissions=True, ignore_mandatory=True)

	def _create(self, plan, **overrides):
		fake_client = MagicMock()
		fake_client.create_vm.return_value = {
			"name": VM_ID, "team": TEAM, "title": "web-1", "status": "Running",
		}
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			result = servers.create_server(
				team=TEAM, region=REGION, title="web-1", plan=plan, **overrides
			)
		return result, fake_client

	def test_trial_creates_server_without_full_profile(self):
		self._fund()
		out, client = self._create(self.plan, vcpus=1, memory_megabytes=2048, disk_gigabytes=20)

		self.assertEqual(out["resource_id"], VM_ID)
		self.assertTrue(out["subscription"])  # metered on the chosen plan
		self.assertEqual(frappe.get_doc("Subscription", out["subscription"]).plan, self.plan)
		# Size flows through from the caller (the form derives it from the plan), untouched.
		self.assertEqual(client.create_vm.call_args.kwargs["memory_megabytes"], 2048)

	def test_requires_a_plan_so_it_is_metered(self):
		self._fund()
		fake_client = MagicMock()
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			with self.assertRaises(frappe.ValidationError):
				servers.create_server(team=TEAM, region=REGION, title="web-1")
		fake_client.create_vm.assert_not_called()

	def test_rejects_when_credits_are_used_up(self):
		# Currency-only profile, no credit grant → zero balance → refused before Atlas.
		fake_client = MagicMock()
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			with self.assertRaises(frappe.ValidationError):
				servers.create_server(team=TEAM, region=REGION, title="web-1", plan=self.plan)
		fake_client.create_vm.assert_not_called()

	def test_enforces_trial_server_cap(self):
		self._fund()
		for i in range(servers.TRIAL_SERVER_LIMIT):
			self._seed_asset(f"trial-seed-{i}")
		fake_client = MagicMock()
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			with self.assertRaises(frappe.ValidationError):
				servers.create_server(team=TEAM, region=REGION, title="web-1", plan=self.plan)
		fake_client.create_vm.assert_not_called()

	def test_terminated_servers_do_not_count_against_cap(self):
		self._fund()
		for i in range(servers.TRIAL_SERVER_LIMIT):
			self._seed_asset(f"dead-{i}", status="Terminated")
		out, _ = self._create(self.plan)
		self.assertEqual(out["resource_id"], VM_ID)

	def test_non_trial_team_still_needs_full_profile(self):
		# Same currency-only profile, but not a trial → the billing-profile gate holds.
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 0)
		self._fund()
		fake_client = MagicMock()
		with patch.object(servers.AtlasClient, "for_region", return_value=fake_client):
			with self.assertRaises(frappe.ValidationError):
				servers.create_server(team=TEAM, region=REGION, title="web-1", plan=self.plan)
		fake_client.create_vm.assert_not_called()
