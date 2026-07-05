# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""list_subscriptions enriches a composed (custom) config for display.

Regression: a composed subscription carries no Plan, so the dashboard showed it with
no price ("—") and only its region — the resource shape and locked price were lost.
It now surfaces the open segment's locked rate and a 'Profile — specs' title."""

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.api.dashboard.invoices import list_subscriptions
from central.billing.catalog import subscriptions
from central.billing.catalog.pricing import set_catalog_rate
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
)

TEAM = "team-dash-subs"
CLUSTER = "ap-south-1"
GENERAL = [
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
]
CONFIG_TOTAL = 3400  # 2*500 + 8*250 + 40*10


class TestDashboardSubscriptions(IntegrationTestCase):
	def setUp(self):
		ensure_atlas_instance(CLUSTER)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		for resource_type, rate in (("Compute", 500), ("Memory", 250), ("Disk", 10)):
			set_catalog_rate("Resource Type", resource_type, "INR", rate)
		self._clear_team_subscriptions()
		frappe.set_user("Administrator")

	def _clear_team_subscriptions(self):
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)

	def _row(self, rows, sub_name):
		return next(r for r in rows if r["name"] == sub_name)

	def test_composed_row_shows_locked_rate_and_spec_title(self):
		# create_subscription (not provision) skips headroom — no trust tier needed here.
		sub = subscriptions.create_subscription(
			TEAM, CLUSTER, plan=None, pricing_mode="Composed",
			includes=GENERAL, sub_category="General", resource_id="res-dash-composed",
		)
		row = self._row(list_subscriptions(TEAM), sub.name)

		# Price is the open segment's locked rate, not a missing Plan rate.
		self.assertEqual(row["monthly_rate"], CONFIG_TOTAL)
		self.assertEqual(row["currency"], "INR")
		# Title carries the profile + the resource shape, not just the region.
		self.assertEqual(row["plan_title"], "General — 2 vCPU · 8 GB RAM · 40 GB disk")

	def test_preset_row_unchanged(self):
		# Regression guard: a preset still shows its Plan title + flat rate.
		plan = make_plan(
			"dash-preset", rates=[{"cluster": "", "currency": "INR", "rate": 1500}], title="Starter"
		)
		sub = subscriptions.create_subscription(TEAM, CLUSTER, plan=plan, resource_id="res-dash-preset")
		row = self._row(list_subscriptions(TEAM), sub.name)

		self.assertEqual(row["plan_title"], "Starter")
		self.assertEqual(row["monthly_rate"], 1500)
