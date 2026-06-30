# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Composed subscription: composition on the Subscription, whole-config rate locked,
single billed line (#80)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.api.admin.catalog import update_component_rate
from central.billing.catalog import subscriptions
from central.billing.catalog.pricing import set_catalog_rate
from central.billing.revenue.invoicing import generate_team_invoice
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)

TEAM = "team-composed"
CLUSTER = "ap-south-1"
# General profile is ratio 4: 2 vCPU needs 8 GB. Seeded INR card: Compute 500,
# Memory 250, Disk 10 -> 2*500 + 8*250 + 40*10 = 3400.
GENERAL = [
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
]
CONFIG_TOTAL = 3400


class TestComposedSubscription(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(CLUSTER)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		set_team_tier(TEAM, max_spend=1_000_000)  # ample headroom — provision enforces it (#83)
		# Reset the INR component card to a known baseline (a prior test may have
		# re-priced a component, and the seed only fills gaps).
		for resource_type, rate in (("Compute", 500), ("Memory", 250), ("Disk", 10)):
			set_catalog_rate("Resource Type", resource_type, "INR", rate)
		self._clear_team_subscriptions()

	def _clear_team_subscriptions(self):
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.db.delete("Invoice", {"team": TEAM})

	def _changes(self, sub, change_type=None):
		filters = {"subscription": sub}
		if change_type:
			filters["change_type"] = change_type
		return frappe.get_all(
			"Subscription Change", filters=filters, fields=["locked_rate", "currency", "new_value", "change_type"]
		)

	def test_provision_composed_locks_summed_config_rate(self):
		out = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		sub = frappe.get_doc("Subscription", out["subscription"])
		self.assertEqual(sub.pricing_mode, "Composed")
		self.assertIsNone(sub.plan)
		self.assertEqual(sub.sub_category, "General")
		self.assertEqual(len(sub.includes), 3)

		created = self._changes(sub.name, "Created")
		self.assertEqual(len(created), 1)
		self.assertEqual(created[0].locked_rate, CONFIG_TOTAL)  # Σ(qty × component_rate)
		self.assertEqual(created[0].currency, "INR")
		self.assertEqual(created[0].new_value, "Custom: 2 vCPU · 8 GB RAM · 40 GB disk")
		self.assertEqual(out["locked_rate"], CONFIG_TOTAL)

	def test_composed_invoice_is_one_prorated_line(self):
		# Provision at the start of a full month, bill that whole month.
		subscriptions.provision_composed_subscription(
			TEAM, CLUSTER, GENERAL, "General", start_date="2026-04-01"
		)
		invoice = generate_team_invoice(TEAM, "2026-04-01", "2026-04-30")
		doc = frappe.get_doc("Invoice", invoice)
		self.assertEqual(len(doc.items), 1)
		line = doc.items[0]
		self.assertEqual(line.rate, CONFIG_TOTAL)
		self.assertEqual(line.amount, CONFIG_TOTAL)  # full month → no proration discount
		self.assertEqual(line.plan, "Custom: 2 vCPU · 8 GB RAM · 40 GB disk")

	def test_grandfathering_holds_after_component_rate_change(self):
		out = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		# An admin bumps the Compute component rate.
		frappe.set_user("Administrator")
		update_component_rate("Compute", "INR", 900)

		# The running config still bills its locked total — the change row is untouched.
		created = self._changes(out["subscription"], "Created")[0]
		self.assertEqual(created.locked_rate, CONFIG_TOTAL)

		# Only a fresh provision picks up the new rate: 2*900 + 8*250 + 40*10 = 4200.
		fresh = subscriptions.provision_composed_subscription(
			TEAM, CLUSTER, GENERAL, "General", resource_id="res-fresh-rate"
		)
		self.assertEqual(fresh["locked_rate"], 4200)

	def test_off_ratio_provision_rejected(self):
		bad = [
			{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
			{"resource_type": "Memory", "quantity": 4, "unit": "GB"},  # General needs 8
		]
		with self.assertRaises(frappe.ValidationError):
			subscriptions.provision_composed_subscription(TEAM, CLUSTER, bad, "General")

	def test_preset_subscription_still_one_flat_line(self):
		# Regression: a preset bills its single flat Plan rate, unchanged.
		plan = make_plan("preset-regression", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		subscriptions.create_subscription(
			TEAM, CLUSTER, plan=plan, start_date="2026-05-01"
		)
		invoice = generate_team_invoice(TEAM, "2026-05-01", "2026-05-31")
		doc = frappe.get_doc("Invoice", invoice)
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(doc.items[0].rate, 1500)
		self.assertEqual(doc.items[0].plan, plan)
