# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Staging trial teams provision servers on free welcome credits.

A team flagged `is_staging_trial` creates servers without a complete billing profile: it needs
only a billing currency, a plan (so usage meters against its credits), unspent credits,
and room under the `TRIAL_SERVER_LIMIT` cap. Size and price come from the chosen plan,
exactly as a normal create — the New Server form is what limits a trial to the entry
tiers. Non-trial teams are unaffected: they still need a complete profile."""

from unittest.mock import patch

import frappe

from central.billing.revenue import credits
from central.billing.tests.provisioning import create_billed_server
from central.billing.tests.utils import (
	BillingTestCase as IntegrationTestCase,
)
from central.billing.tests.utils import (
	ensure_atlas_instance,
	ensure_team,
	isolate_trial_plans,
	make_plan,
)

TEAM = "team-trial-provisioning"
REGION = "ap-south-1"
VM_ID = "vm-trial-test"


class TestTrialProvisioning(IntegrationTestCase):
	_TRACKED = (*IntegrationTestCase._TRACKED, "Resource Action", "Pilot Credential")

	def setUp(self):
		isolate_trial_plans(self)
		self.team = "test-trial-" + frappe.generate_hash(length=8)
		ensure_atlas_instance(REGION)
		ensure_team(self.team)
		frappe.db.set_value("Team", self.team, "is_staging_trial", 1)
		self._minimal_profile(self.team, "INR")
		# A 1 vCPU / 2 GB / 10 GB plan — the size the VM must take, whatever the caller asks.
		self.plan = self._fresh_plan(
			"trial-starter",
			[
				{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": 2, "unit": "GB"},
				{"resource_type": "Disk", "quantity": 10, "unit": "GB"},
			],
			rate=500,
		)
		self._reset_team()
		frappe.set_user("Administrator")

	def _fresh_plan(self, name, includes, rate):
		"""make_plan, but with the plan's child `Plan Includes` cleared first and after.
		make_plan's force-delete doesn't cascade to that child table, so committed reruns
		would otherwise stack duplicate rows and inflate the plan's derived size."""
		frappe.db.delete("Plan Includes", {"parent": name})
		self.addCleanup(frappe.db.delete, "Plan Includes", {"parent": name})
		return make_plan(name, includes=includes, rates=[{"cluster": "", "currency": "INR", "rate": rate}])

	def _minimal_profile(self, team, currency):
		"""A currency-only Billing Profile — the state signup leaves a trial team in."""
		if frappe.db.exists("Billing Profile", team):
			frappe.db.set_value("Billing Profile", team, "currency", currency)
			return
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, "currency": currency})
		doc.insert(ignore_permissions=True, ignore_mandatory=True)

	def _reset_team(self):
		for name in frappe.get_all("Subscription", filters={"team": self.team}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.db.delete("Asset", {"team": self.team})

	def _fund(self, amount=2500):
		credits.grant_promotional_credits(self.team, amount, "INR")

	def _seed_asset(self, resource_id, status="Running"):
		doc = frappe.get_doc(
			{"doctype": "Asset", "team": self.team, "cluster": REGION, "title": resource_id, "status": status}
		)
		doc.flags.name_set = True
		doc.name = resource_id
		doc.insert(ignore_permissions=True, ignore_mandatory=True)

	def _create(self, plan, **overrides):
		return create_billed_server(self.team, REGION, plan, **overrides)

	def test_trial_creates_metered_server_at_plan_size(self):
		self._fund()
		action, client = self._create(self.plan)
		self.assertEqual(action.status, "Succeeded")
		subscription = frappe.get_doc("Subscription", {"asset_id": action.asset})
		self.assertEqual(subscription.plan, self.plan)
		size = client.create_vm.call_args.args[0]
		self.assertEqual((size["cpu_millicores"], size["memory_mib"], size["disk_mib"]), (1000, 2048, 10240))

	def test_rejects_plan_outside_the_trial_allowlist(self):
		self._fund()
		other = self._fresh_plan("trial-enterprise", None, rate=9000)
		frappe.db.set_value("Plan", self.plan, "available_on_trial", 1)
		with self.assertRaises(frappe.ValidationError):
			self._create(other)
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team}))

	def test_requires_a_plan_so_it_is_metered(self):
		self._fund()
		with self.assertRaises(frappe.ValidationError):
			self._create(None)

	def test_rejects_when_credits_are_used_up(self):
		with self.assertRaises(frappe.ValidationError):
			self._create(self.plan)
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team}))

	def test_enforces_trial_server_cap(self):
		self._fund()
		for i in range(3):
			self._seed_asset(f"trial-seed-{i}")
		with self.assertRaises(frappe.ValidationError):
			self._create(self.plan)

	def test_pending_requests_count_against_trial_cap(self):
		self._fund()
		with patch("central.billing.tests.provisioning._process_locked"):
			for index in range(3):
				self._create(self.plan, title=f"trial-{index}")
			with self.assertRaises(frappe.ValidationError):
				self._create(self.plan, title="trial-over-cap")

	def test_terminated_servers_do_not_count_against_cap(self):
		self._fund()
		for i in range(3):
			self._seed_asset(f"dead-{i}", status="Terminated")
		action, _ = self._create(self.plan)
		self.assertEqual(action.status, "Succeeded")

	def test_staging_trial_profile_is_autocompleted(self):
		# The console blocks server creation until the billing profile is complete; a
		# trial's currency-only profile is filled with staging placeholders so it passes.
		from central.billing.api.dashboard._shared import _profile_complete
		from central.billing.payments.provisioning import complete_trial_billing_profile

		self.assertFalse(_profile_complete(self.team))  # currency only
		complete_trial_billing_profile(self.team)
		self.assertTrue(_profile_complete(self.team))

	def test_autocomplete_skips_non_trial_team(self):
		from central.billing.api.dashboard._shared import _profile_complete
		from central.billing.payments.provisioning import complete_trial_billing_profile

		frappe.db.set_value("Team", self.team, "is_staging_trial", 0)
		complete_trial_billing_profile(self.team)
		self.assertFalse(_profile_complete(self.team))  # left incomplete for a normal team

	def test_team_save_autocompletes_trial_profile(self):
		# Flipping the flag in Desk (a Team save) completes the profile via the on_update hook.
		from central.billing.api.dashboard._shared import _profile_complete

		self.assertFalse(_profile_complete(self.team))
		frappe.get_doc("Team", self.team).save(ignore_permissions=True)
		self.assertTrue(_profile_complete(self.team))

	def test_non_trial_team_still_needs_full_profile(self):
		# Same currency-only profile, but not a trial → the billing-profile gate holds.
		frappe.db.set_value("Team", self.team, "is_staging_trial", 0)
		self._fund()
		with self.assertRaises(frappe.ValidationError):
			self._create(self.plan)
		self.assertFalse(frappe.db.exists("Resource Action", {"team": self.team}))
