# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The reads behind the reworked Billing Overview.

Three things worth pinning down. The forecast must carry its measured/estimated
split, because the whole point of the card is that a bill which is part guesswork
does not read like a bill. The next-payment outlook must warn only where the team's
own state entails failure, and never claim a charge will succeed. And the locked-price
read must not report a fallen catalog price as a negative saving.
"""

import frappe

from central.billing.api import dashboard
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_billing_subscription,
	make_plan,
	reset_gateway_roster,
	set_team_tier,
)

TEAM = "team-overview"
CLUSTER = "ap-south-1"
PLAN = "bundle-overview-test"


class OverviewBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN, rates=[{"cluster": "", "currency": "INR", "rate": 3000}])
		reset_gateway_roster()
		self._purge()
		self.today = frappe.utils.getdate()
		self.month_start = frappe.utils.get_first_day(self.today)

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Credit Ledger Entry", "Payment Method", "Tax Profile", "Billing Profile"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _provision(self, rate=3000):
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(sub, "Created", rate, f"{self.month_start} 00:00:00", plan=PLAN)
		return sub


class TestForecastBasis(OverviewBase):
	def test_forecast_carries_the_measured_estimated_split(self):
		self._provision(rate=3000)

		fc = dashboard.get_forecast(TEAM)

		# A fixed bundle over elapsed days is arithmetic on a locked rate — a fact,
		# not an inference. Nothing here should read as an estimate.
		self.assertEqual(fc["measured"], 3000.0)
		self.assertEqual(fc["estimated"], 0.0)
		self.assertFalse(fc["has_estimates"])
		self.assertEqual(fc["measured"] + fc["estimated"], fc["subtotal"])

	def test_every_line_says_where_its_quantity_came_from(self):
		self._provision(rate=3000)

		fc = dashboard.get_forecast(TEAM)

		self.assertTrue(fc["line_items"])
		for line in fc["line_items"]:
			self.assertIn(line["basis"], ("Measured", "Estimated", "Assumed"))

	def test_a_stored_invoice_line_is_always_measured(self):
		# By the time an invoice is issued nothing about it is still inferred, so a
		# line item read off the document reports itself as a fact.
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": str(self.month_start),
				"period_end": str(frappe.utils.get_last_day(self.today)),
				"currency": "INR",
				"subtotal": 1000,
				"total": 1000,
				"items": [{"resource_type": "bundle", "plan": PLAN, "rate": 1000, "days": 30, "amount": 1000}],
			}
		).insert(ignore_permissions=True)

		detail = dashboard.get_invoice(invoice.name)

		self.assertEqual(detail["items"][0]["basis"], "Measured")


class TestNextPayment(OverviewBase):
	def test_no_payment_method_is_reported_as_a_blocker(self):
		self._provision(rate=3000)

		out = dashboard.get_next_payment(TEAM)

		self.assertEqual(out["amount"], 3000.0)
		self.assertFalse(out["will_auto_charge"])
		codes = [b["code"] for b in out["blockers"]]
		self.assertIn("no_settlement_source", codes)

	def test_a_blocker_says_what_to_do_about_it(self):
		# The engine's own wording is written for an operator reading a book of
		# teams. What reaches a customer has to tell them what to do.
		self._provision(rate=3000)

		blocker = dashboard.get_next_payment(TEAM)["blockers"][0]

		self.assertTrue(blocker["fix"])
		self.assertNotIn("dunning", blocker["fix"].lower())

	def test_a_bill_over_the_silent_ceiling_is_flagged_before_the_first(self):
		complete_billing_profile(TEAM, currency="INR")
		frappe.db.set_value("Billing Profile", TEAM, "collection_mode", "Auto Charge")
		# Tier cap under the bill: the charge path would refuse this off-session, so
		# the customer is told now rather than after a failed debit.
		set_team_tier(TEAM, max_spend=1000)
		self._provision(rate=3000)

		out = dashboard.get_next_payment(TEAM)

		self.assertIn("over_silent_threshold", [b["code"] for b in out["blockers"]])

	def test_nothing_due_is_not_a_blocker(self):
		out = dashboard.get_next_payment(TEAM)

		self.assertEqual(out["amount"], 0.0)

	def test_the_schedule_publishes_the_escalation_ladder(self):
		self._provision(rate=3000)

		schedule = dashboard.get_payment_schedule(TEAM)

		self.assertTrue(schedule["if_unpaid"])
		for stage in schedule["if_unpaid"]:
			self.assertIn("date", stage)
			self.assertIn("stage", stage)
		self.assertEqual(schedule["notices"], [])


class TestCycleCosts(OverviewBase):
	def test_cost_is_reported_per_resource(self):
		self._provision(rate=3000)

		out = dashboard.get_cycle_costs(TEAM)

		self.assertEqual(len(out["items"]), 1)
		self.assertEqual(out["items"][0]["amount"], 3000.0)
		self.assertEqual(out["total"], 3000.0)
		self.assertEqual(out["currency"], "INR")

	def test_nothing_running_costs_nothing(self):
		out = dashboard.get_cycle_costs(TEAM)

		self.assertEqual(out["items"], [])
		self.assertEqual(out["total"], 0.0)


class TestLockedPrices(OverviewBase):
	def test_a_rate_below_list_is_reported_as_a_saving(self):
		# Catalog says 3000; this segment locked at 2000 before a rise.
		self._provision(rate=2000)

		out = dashboard.get_locked_prices(TEAM)

		row = out["rows"][0]
		self.assertEqual(row["locked_rate"], 2000.0)
		self.assertEqual(row["list_rate"], 3000.0)
		self.assertEqual(row["saving"], 1000.0)
		self.assertFalse(row["above_list"])
		self.assertEqual(out["monthly_saving"], 1000.0)
		self.assertEqual(out["annual_saving"], 12000.0)
		self.assertEqual(out["protected_count"], 1)

	def test_a_fallen_catalog_price_is_never_a_negative_saving(self):
		# The lock cuts both ways: locked at 5000, catalog since down to 3000. The
		# customer is over list and is told so — not shown a saving of -2000.
		self._provision(rate=5000)

		out = dashboard.get_locked_prices(TEAM)

		row = out["rows"][0]
		self.assertEqual(row["saving"], 0.0)
		self.assertTrue(row["above_list"])
		self.assertEqual(row["above_list_by"], 2000.0)
		self.assertEqual(out["monthly_saving"], 0.0)
		self.assertEqual(out["protected_count"], 0)
		self.assertEqual(out["above_list_count"], 1)

	def test_the_locked_rate_is_what_the_subscription_list_quotes(self):
		# A grandfathered team must not be shown today's catalog rate as its price:
		# the open segment is what it will actually be billed (ADR 0010).
		self._provision(rate=2000)

		row = dashboard.list_subscriptions(TEAM)[0]

		self.assertEqual(row["monthly_rate"], 2000.0)
		self.assertTrue(row["resource_id"])
