# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Projecting one team over one period."""

import frappe

from central.billing.projection import engine
from central.billing.projection.basis import ESTIMATED, MEASURED
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_metered_plan,
	make_plan,
)

TEAM = "team-projection-engine"
CLUSTER = "ap-south-1"
PLAN = "bundle-projection-engine"


class ProjectionTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN, includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}])
		make_metered_plan(
			"meter-transfer-engine",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Invoice", "Usage Rollup"):
			frappe.db.delete(dt, {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()


class TestProjectingAPeriod(ProjectionTestBase):
	def test_a_future_month_is_priced_from_the_locked_rate(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")

		self.assertEqual(out["invoice"]["subtotal"], 12000.0)
		self.assertEqual(out["invoice"]["measured"], 12000.0)
		self.assertEqual(out["invoice"]["estimated"], 0.0)
		self.assertFalse(out["invoice"]["has_estimates"])

	def test_fixed_lines_are_measured_even_for_a_month_that_has_not_started(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertTrue(all(li["basis"] == MEASURED for li in out["invoice"]["lines"]))

	def test_a_team_with_nothing_running_projects_no_invoice(self):
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertIsNone(out["invoice"])

	def test_projecting_writes_nothing(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		before = frappe.db.count("Invoice", {"team": TEAM})
		engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertEqual(frappe.db.count("Invoice", {"team": TEAM}), before)

	def test_the_period_and_the_asking_date_are_reported_back(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertEqual(out["period_start"], "2026-09-01")
		self.assertEqual(out["as_of"], "2026-08-06")
		self.assertEqual(out["currency"], "INR")


class TestEstimatedUsageReachesTheInvoice(ProjectionTestBase):
	def _rollup(self, month, quantity):
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": frappe.db.get_value("Subscription", self.sub, "asset_id"),
				"team": TEAM,
				"cluster": CLUSTER,
				"resource_type": "Transfer",
				"meter_type": "Counter",
				"period_start": f"{month}-01 00:00:00",
				"period_end": f"{month}-28 23:59:59",
				"quantity": quantity,
				"unit": "GB",
				"currency": "INR",
				"locked_allowance": 100,
				"locked_rate": 0.5,
				"idempotency_key": f"proj:{month}",
				"sequence": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_projected_usage_is_billed_and_flagged_as_an_estimate(self):
		# Without this the metered half of the bill silently vanishes for a future month.
		add_segment(self.sub, "Created", 12000, "2026-05-01 00:00:00")
		for month, qty in (("2026-06", 200), ("2026-07", 300), ("2026-08", 400)):
			self._rollup(month, qty)

		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-30")
		invoice = out["invoice"]

		self.assertEqual(invoice["measured"], 12000.0)
		self.assertEqual(invoice["estimated"], 100.0)  # (50 + 100 + 150) / 3
		self.assertEqual(invoice["subtotal"], 12100.0)
		self.assertTrue(invoice["has_estimates"])
		bases = {li["basis"] for li in invoice["lines"]}
		self.assertEqual(bases, {MEASURED, ESTIMATED})


class TestTheCalendar(ProjectionTestBase):
	def test_the_invoice_opens_the_day_after_the_period_closes(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		cal = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")["calendar"]
		self.assertEqual(cal["opens_on"], "2026-10-01")

	def test_both_branches_are_returned_together(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		cal = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")["calendar"]

		self.assertEqual(cal["if_paid_on_time"][0]["stage"], "Settled")
		self.assertEqual(cal["if_paid_on_time"][0]["date"], cal["due_on"])

		stages = [s["stage"] for s in cal["if_never_paid"]]
		self.assertIn("Retry", stages)
		self.assertIn("Overdue", stages)
		self.assertIn("Suspend", stages)
		self.assertIn("Terminate", stages)

	def test_the_ladder_is_dated_from_the_due_date(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		cal = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")["calendar"]
		suspend = [s for s in cal["if_never_paid"] if s["stage"] == "Suspend"][0]
		expected = frappe.utils.add_days(cal["due_on"], suspend["day"])
		self.assertEqual(suspend["date"], str(expected))


class TestInvoicesAlreadyInFlight(ProjectionTestBase):
	def _open_invoice(self, due, dunning_starts_on=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"subscription": self.sub,
					"status": "Open",
					"period_start": "2026-07-01",
					"period_end": "2026-07-31",
					"currency": "INR",
					"subtotal": 5000,
					"total": 5000,
					"expected_collection": 5000,
					"due_date": due,
					"dunning_starts_on": dunning_starts_on,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_an_unpaid_invoice_carries_its_own_ladder(self):
		name = self._open_invoice("2026-08-01")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")

		flight = out["in_flight"]
		self.assertEqual(len(flight), 1)
		self.assertEqual(flight[0]["invoice"], name)
		self.assertEqual(flight[0]["clock_starts_on"], "2026-08-01")
		self.assertEqual(flight[0]["days_in"], 5)
		self.assertTrue(flight[0]["ladder"])

	def test_a_deferred_clock_is_honoured_and_marked(self):
		# We failed to collect, so their escalation restarts later. Counting from the due
		# date instead would charge the customer for our outage.
		self._open_invoice("2026-08-01", dunning_starts_on="2026-08-20")
		frappe.db.commit()
		flight = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")["in_flight"]

		self.assertEqual(flight[0]["clock_starts_on"], "2026-08-20")
		self.assertTrue(flight[0]["clock_deferred"])
		self.assertLess(flight[0]["days_in"], 0)

	def test_a_team_with_nothing_outstanding_has_an_empty_flight(self):
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertEqual(out["in_flight"], [])


class TestOutcomeReachesTheProjection(ProjectionTestBase):
	def test_a_team_with_no_way_to_pay_entails_the_unpaid_branch(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")

		self.assertEqual(out["outcome"]["mode"], "Derived")
		self.assertEqual(out["outcome"]["entailed_branch"], "if_never_paid")
		self.assertIn("no_settlement_source", {f["finding"] for f in out["outcome"]["findings"]})

	def test_both_branches_are_still_returned_when_one_is_entailed(self):
		# Marking an arm must not hide the other: the fork is what the operator came for.
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		cal = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")["calendar"]
		self.assertTrue(cal["if_paid_on_time"])
		self.assertTrue(cal["if_never_paid"])

	def test_optimistic_mode_asserts_settlement_and_derives_nothing(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06", mode="Optimistic")
		self.assertEqual(out["outcome"]["entailed_branch"], "if_paid_on_time")
		self.assertEqual(out["outcome"]["findings"], [])

	def test_an_assumed_outcome_is_carried_through(self):
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(
			TEAM,
			"2026-09-01",
			"2026-09-30",
			today="2026-08-06",
			mode="Assumed",
			assume="never_pays",
		)
		self.assertEqual(out["outcome"]["assumed"], "never_pays")
		self.assertEqual(out["outcome"]["entailed_branch"], "if_never_paid")

	def test_findings_are_derived_from_what_we_would_actually_collect(self):
		# Credits and withholding change the amount the gateway is asked for, so the
		# threshold questions must be asked of that, not of the headline total.
		add_segment(self.sub, "Created", 12000, "2026-06-01 00:00:00")
		frappe.db.commit()
		out = engine.project(TEAM, "2026-09-01", "2026-09-30", today="2026-08-06")
		self.assertEqual(out["invoice"]["expected_collection"], 12000.0)
