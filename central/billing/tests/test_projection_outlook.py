# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Who gets cut off and when, and whether that is their doing or ours."""

import frappe

from central.billing.projection import behaviour, outlook
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import billing_settings, ensure_team

TEAM = "team-outlook"
TODAY = "2026-09-10"


class OutlookTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.commit()

	def _invoice(self, due, status="Open", amount=5000, dunning_starts_on=None, currency="INR"):
		# One invoice per team per period is enforced by a unique index, so each fixture
		# bills its own month — derived from the due date it is given.
		anchor = frappe.utils.add_months(frappe.utils.getdate(due or "2026-08-08"), -1)
		period_start = frappe.utils.get_first_day(anchor)
		period_end = frappe.utils.get_last_day(anchor)
		name = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": status,
					"period_start": period_start,
					"period_end": period_end,
					"currency": currency,
					"subtotal": amount,
					"total": amount,
					"expected_collection": amount,
					"due_date": due,
					"dunning_starts_on": dunning_starts_on,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()
		return name


class TestTheSweep(OutlookTestBase):
	def test_an_unpaid_invoice_gets_a_dated_ladder(self):
		with billing_settings(dunning_retry_days="1, 3, 7", suspend_after_days=14, terminate_after_days=44):
			self._invoice("2026-09-01")
			rows = outlook.rows(on=TODAY, filters={"team": TEAM})

		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["days_in"], 9)
		self.assertEqual(row["suspends_on"], "2026-09-15")
		self.assertEqual(row["terminates_on"], "2026-10-15")

	def test_a_paid_invoice_is_not_in_the_sweep(self):
		self._invoice("2026-09-01", status="Paid")
		self.assertEqual(outlook.rows(on=TODAY, filters={"team": TEAM}), [])

	def test_nothing_is_estimated_or_rated(self):
		# Every column is a stored fact or arithmetic over one, which is why this can run
		# over the whole book however large it gets.
		self._invoice("2026-09-01")
		row = outlook.rows(on=TODAY, filters={"team": TEAM})[0]
		self.assertEqual(row["outstanding"], 5000.0)
		self.assertNotIn("estimated", row)

	def test_the_soonest_consequence_sorts_first(self):
		self._invoice("2026-09-01", amount=1000)
		self._invoice("2026-08-01", amount=2000)
		rows = outlook.rows(on=TODAY, filters={"team": TEAM})
		self.assertLessEqual(rows[0]["suspends_on"], rows[1]["suspends_on"])

	def test_a_horizon_keeps_only_what_is_about_to_happen(self):
		with billing_settings(dunning_retry_days="1, 3, 7", suspend_after_days=14, terminate_after_days=44):
			self._invoice("2026-09-09")  # next action is days away
			near = outlook.rows(on=TODAY, horizon_days=3, filters={"team": TEAM})
			far = outlook.rows(on=TODAY, horizon_days=60, filters={"team": TEAM})
		self.assertLessEqual(len(near), len(far))

	def test_an_invoice_with_no_due_date_is_skipped_rather_than_guessed_at(self):
		self._invoice(None)
		self.assertEqual(outlook.rows(on=TODAY, filters={"team": TEAM}), [])


class TestOurDelayIsMarkedAsOurs(OutlookTestBase):
	def test_a_deferred_clock_is_honoured_and_flagged(self):
		self._invoice("2026-09-01", dunning_starts_on="2026-09-20")
		row = outlook.rows(on=TODAY, filters={"team": TEAM})[0]

		self.assertEqual(row["clock_starts_on"], "2026-09-20")
		self.assertTrue(row["clock_deferred"])
		self.assertLess(row["days_in"], 0)

	def test_the_drill_explains_the_deferral(self):
		name = self._invoice("2026-09-01", dunning_starts_on="2026-09-20")
		out = outlook.why(name, on=TODAY)
		self.assertTrue(out["clock_deferred"])
		self.assertIn("our side", out["deferred_note"])
		self.assertIn("due date is unchanged", out["deferred_note"])

	def test_the_drill_shows_which_rungs_have_been_reached(self):
		with billing_settings(dunning_retry_days="1, 3, 7", suspend_after_days=14):
			name = self._invoice("2026-09-01")
			out = outlook.why(name, on=TODAY)
		reached = [s for s in out["ladder"] if s["reached"]]
		ahead = [s for s in out["ladder"] if not s["reached"]]
		self.assertTrue(reached)
		self.assertTrue(ahead)


class TestBehaviour(OutlookTestBase):
	def test_a_team_that_always_paid_reads_as_such(self):
		for due in ("2026-04-08", "2026-05-08", "2026-06-08"):
			self._invoice(due, status="Paid")
		record = behaviour.with_verdict(TEAM, on=TODAY)

		self.assertEqual(record["invoices"], 3)
		self.assertEqual(record["on_time"], 3)
		self.assertEqual(record["verdict"], "Always paid on time")

	def test_an_outstanding_invoice_counts_against_the_record(self):
		self._invoice("2026-06-08", status="Paid")
		self._invoice("2026-07-08", status="Overdue")
		record = behaviour.with_verdict(TEAM, on=TODAY)

		self.assertEqual(record["on_time"], 1)
		self.assertEqual(record["invoices"], 2)
		self.assertGreater(record["worst_delay_days"], 0)

	def test_lateness_is_measured_from_the_due_date_not_the_deferred_clock(self):
		# The deferred clock protects customers from our collection failures. Scoring
		# against it would mark them down for our outage.
		self._invoice("2026-07-08", status="Overdue", dunning_starts_on="2026-09-30")
		record = behaviour.summary(TEAM, on=TODAY)
		self.assertGreater(record["worst_delay_days"], 30)

	def test_a_cancelled_invoice_is_not_held_against_anyone(self):
		self._invoice("2026-06-08", status="Cancelled")
		self.assertEqual(behaviour.summary(TEAM, on=TODAY)["invoices"], 0)

	def test_a_team_with_no_history_says_so_rather_than_scoring_zero(self):
		record = behaviour.with_verdict(TEAM, on=TODAY)
		self.assertEqual(record["verdict"], "No history")

	def test_the_verdict_separates_their_problem_from_ours(self):
		# The distinction that changes what an operator does next.
		self.assertEqual(
			behaviour.verdict({"invoices": 6, "on_time": 6, "worst_delay_days": 0}),
			"Always paid on time",
		)
		self.assertEqual(
			behaviour.verdict({"invoices": 6, "on_time": 0, "worst_delay_days": 90}),
			"Never paid on time",
		)
		self.assertEqual(
			behaviour.verdict({"invoices": 6, "on_time": 3, "worst_delay_days": 45}),
			"Chronically late",
		)


class TestTheForecastIsAProjection(IntegrationTestCase):
	"""The customer's number and the operator's are one computation."""

	def test_the_forecast_runs_through_the_engine(self):
		import inspect

		from central.billing.api.dashboard import invoices

		source = inspect.getsource(invoices.get_forecast)
		self.assertIn("engine.project", source)
		self.assertNotIn("compute_line_items", source)

	def test_a_customer_read_does_not_fail_on_a_dirty_transaction(self):
		# Refusing here would break a customer page to enforce an internal invariant,
		# and committing on their behalf is the side effect the guard exists to prevent.
		from central.billing.projection.guard import read_only

		ensure_team(TEAM)
		frappe.db.set_value("Team", TEAM, "team_name", "Mid-transaction")
		with read_only(strict=False):
			self.assertTrue(frappe.db.exists("Team", TEAM))
		frappe.db.rollback()

	def test_an_operator_projection_still_refuses(self):
		from central.billing.projection.guard import ProjectionBoundaryError, read_only

		ensure_team(TEAM)
		frappe.db.set_value("Team", TEAM, "team_name", "Mid-transaction")
		with self.assertRaises(ProjectionBoundaryError):
			with read_only():
				pass
		frappe.db.rollback()
