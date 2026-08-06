# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Metered usage for periods that have not happened, and saying so."""

import frappe
from central.billing.projection import estimate
from central.billing.projection.basis import ESTIMATED, MEASURED, split_totals
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	ensure_team,
	make_metered_plan,
	make_plan,
	seed_running_resource,
)

TEAM = "team-projection-estimate"
CLUSTER = "ap-south-1"
PLAN = "bundle-projection-estimate"
RESOURCE = "srv-projection-estimate"


class EstimateTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN, includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}])
		make_metered_plan(
			"meter-transfer-projection",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		self._purge()
		seed_running_resource(TEAM, RESOURCE, CLUSTER, PLAN, rate=1000, currency="INR")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Usage Rollup", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def _rollup(self, month: str, quantity: float):
		"""One grandfathered transfer rollup for `month` (YYYY-MM), 100 GB allowance."""
		frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": RESOURCE,
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
				"idempotency_key": f"{RESOURCE}:Counter:{month}-01",
				"sequence": 0,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()


class TestFuturePeriods(EstimateTestBase):
	def test_a_month_that_has_not_started_is_inferred_from_the_trailing_window(self):
		# 200 / 300 / 400 GB against a 100 GB allowance at 0.5/GB → 50 / 100 / 150.
		for month, qty in (("2026-03", 200), ("2026-04", 300), ("2026-05", 400)):
			self._rollup(month, qty)

		lines = estimate.metered_lines(
			TEAM, [CLUSTER], "2026-06-01", "2026-06-30", today="2026-05-20"
		)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["basis"], ESTIMATED)
		self.assertEqual(lines[0]["amount"], 100.0)  # (50 + 100 + 150) / 3
		self.assertIn("3-month average", lines[0]["estimated_from"])

	def test_no_history_projects_no_line_rather_than_a_zero_one(self):
		# Silence is not evidence of zero usage; asserting zero would be a claim we
		# cannot support, and it is the claim that reassures.
		lines = estimate.metered_lines(
			TEAM, [CLUSTER], "2026-06-01", "2026-06-30", today="2026-05-20"
		)
		self.assertEqual(lines, [])

	def test_usage_inside_the_allowance_leaves_nothing_to_project(self):
		for month in ("2026-03", "2026-04", "2026-05"):
			self._rollup(month, 80)  # under the 100 GB allowance
		lines = estimate.metered_lines(
			TEAM, [CLUSTER], "2026-06-01", "2026-06-30", today="2026-05-20"
		)
		self.assertEqual(lines, [])


class TestPeriodsInFlight(EstimateTestBase):
	def test_a_part_elapsed_month_is_scaled_to_its_full_length(self):
		# 150 GB landed by the 10th of a 30-day month → 50 GB over allowance → ₹25,
		# projected across 30/10 = 3x.
		self._rollup("2026-06", 150)
		lines = estimate.metered_lines(
			TEAM, [CLUSTER], "2026-06-01", "2026-06-30", today="2026-06-10"
		)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["basis"], ESTIMATED)
		self.assertEqual(lines[0]["amount"], 75.0)
		self.assertIn("10 of 30 days", lines[0]["estimated_from"])


class TestClosedPeriods(EstimateTestBase):
	def test_a_finished_month_is_measured_not_estimated(self):
		self._rollup("2026-06", 300)
		lines = estimate.metered_lines(
			TEAM, [CLUSTER], "2026-06-01", "2026-06-30", today="2026-07-05"
		)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["basis"], MEASURED)
		self.assertEqual(lines[0]["amount"], 100.0)  # (300 - 100) * 0.5
		self.assertNotIn("estimated_from", lines[0])


class TestSplitTotals(IntegrationTestCase):
	def test_totals_are_reported_by_provenance(self):
		totals = split_totals(
			[
				{"amount": 12000.0, "basis": MEASURED},
				{"amount": 4800.0, "basis": MEASURED},
				{"amount": 1120.0, "basis": ESTIMATED},
			]
		)
		self.assertEqual(totals["measured"], 16800.0)
		self.assertEqual(totals["estimated"], 1120.0)
		self.assertTrue(totals["has_estimates"])

	def test_a_wholly_measured_invoice_is_flagged_as_such(self):
		totals = split_totals([{"amount": 500.0, "basis": MEASURED}])
		self.assertFalse(totals["has_estimates"])
		self.assertEqual(totals["estimated"], 0.0)

	def test_a_line_with_no_basis_counts_as_measured(self):
		# Fixed lines come off the real line engine without a basis; they are facts.
		self.assertEqual(split_totals([{"amount": 300.0}])["measured"], 300.0)
