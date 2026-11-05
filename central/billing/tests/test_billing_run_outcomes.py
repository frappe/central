# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The run keeps what it did per team, retries a failure and explains every team it skipped."""

from unittest.mock import patch

import frappe

from central.billing.doctype.billing_run_team.billing_run_team import record_outcome
from central.billing.platform import readiness
from central.billing.report.billing_activity import billing_activity
from central.billing.report.billing_run_coverage import billing_run_coverage
from central.billing.revenue import invoicing
from central.billing.revenue.invoicing import run
from central.billing.states import record_team_event, transition
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	billing_settings,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-run-outcome"
OTHER_TEAM = "team-run-outcome-other"
CLUSTER = "ap-south-1"
PLAN = "bundle-run-outcome"
PERIOD = ("2026-06-01", "2026-06-30")
RATE = "central.billing.revenue.invoicing.generate.rate_team_period"


def _outcome():
	return frappe.db.get_value(
		"Billing Run Team",
		{"team": TEAM, "period_end": PERIOD[1]},
		["outcome", "reason", "invoice"],
		as_dict=True,
	)


class TestBillingRunOutcomes(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")

	def _events(self, event_type):
		return frappe.db.count("Billing Event", {"team": TEAM, "event_type": event_type})

	def test_an_invoiced_team_is_recorded(self):
		name = run.draft_team_invoice(TEAM, *PERIOD)[0]

		self.assertEqual((_outcome().outcome, _outcome().invoice), ("Invoiced", name))
		self.assertEqual(self._events("Invoice Generated"), 1)

	def test_a_failure_keeps_its_reason_and_the_hourly_retry_recovers_it(self):
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			self.assertEqual(run.draft_team_invoice(TEAM, *PERIOD), [])

		self.assertEqual((_outcome().outcome, _outcome().reason), ("Failed", "No rate for Storage"))
		self.assertEqual(self._events("Invoice Generation Failed"), 1)
		self.assertEqual(len([v for v in readiness.check_teams_were_invoiced() if v.team == TEAM]), 1)

		run.retry_failed_invoices()

		self.assertEqual(_outcome().outcome, "Invoiced")
		self.assertTrue(frappe.db.exists("Invoice", {"team": TEAM, "period_end": PERIOD[1]}))

	def test_the_hourly_retry_takes_the_longest_waiting_failure_first(self):
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			run.draft_team_invoice(TEAM, *PERIOD)
		frappe.db.set_value(
			"Billing Run Team", {"team": TEAM}, "modified", "2000-01-01", update_modified=False
		)
		ensure_team(OTHER_TEAM)
		record_outcome(OTHER_TEAM, PERIOD[1], "Failed", reason="Retried later")

		with patch.object(run, "PAGE_SIZE", 1):
			run.retry_failed_invoices()

		self.assertEqual(_outcome().outcome, "Invoiced")

	def test_a_retry_with_the_same_error_records_one_event(self):
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			run.draft_team_invoice(TEAM, *PERIOD)
			run.draft_team_invoice(TEAM, *PERIOD)

		self.assertEqual(self._events("Invoice Generation Failed"), 1)

	def test_a_run_with_a_failed_team_does_not_complete(self):
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			run.draft_team_invoice(TEAM, *PERIOD)
			status = run.billing_run_status(today="2026-07-01")
		self.assertGreaterEqual(status["failures"], 1)

	def test_a_month_below_the_minimum_makes_no_invoice(self):
		with billing_settings(minimum_invoice_amounts=[{"currency": "INR", "amount": 5000}]):
			self.assertEqual(run.draft_team_invoice(TEAM, *PERIOD), [])
			run.draft_team_invoice(TEAM, *PERIOD)

		self.assertFalse(frappe.db.exists("Invoice", {"team": TEAM, "period_end": PERIOD[1]}))
		self.assertEqual(_outcome().outcome, "Below Minimum")
		self.assertIn("written off", _outcome().reason)
		self.assertEqual(self._events("Invoice Skipped Below Minimum"), 1)

	def test_a_month_at_or_above_the_minimum_is_invoiced(self):
		with billing_settings(minimum_invoice_amounts=[{"currency": "INR", "amount": 1}]):
			self.assertTrue(run.draft_team_invoice(TEAM, *PERIOD))


class TestBillingRunCoverage(IntegrationTestCase):
	def _row(self, team):
		rows = billing_run_coverage.classify_teams(PERIOD[1])
		return next(row for row in rows if row["team"] == team)

	def test_every_team_gets_a_reason(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			run.draft_team_invoice(TEAM, *PERIOD)

		row = self._row(TEAM)

		self.assertEqual(row["stage"], billing_run_coverage.NEEDS_ACTION)
		self.assertIn("No rate for Storage", row["reason"])
		rows = billing_run_coverage.classify_teams(PERIOD[1])
		self.assertTrue(all(row["reason"] for row in rows))

	def test_with_no_month_the_report_shows_the_month_that_just_closed(self):
		with patch.object(
			billing_run_coverage, "classify_teams", wraps=billing_run_coverage.classify_teams
		) as classify:
			billing_run_coverage.execute({})

		classify.assert_called_once_with(run.billing_period()[1])

	def test_a_month_below_the_minimum_is_its_own_result(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		with billing_settings(minimum_invoice_amounts=[{"currency": "INR", "amount": 5000}]):
			run.draft_team_invoice(TEAM, *PERIOD)

		self.assertEqual(self._row(TEAM)["stage"], billing_run_coverage.BELOW_MINIMUM)

	def test_a_held_invoice_is_waiting_with_its_reason(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		invoice = invoicing.generate_draft_invoice(subscription, *PERIOD)
		frappe.db.set_value("Invoice", invoice, "hold_reason", "Accounting Sync")

		row = self._row(TEAM)

		self.assertEqual(row["stage"], billing_run_coverage.WAITING)
		self.assertIn("Accounting Sync", row["reason"])

	def test_missing_manual_settings_are_named(self):
		with billing_settings(raven_site_url="", raven_channel_id="", operator_alert_emails=""):
			frappe.clear_document_cache("Billing Settings", "Billing Settings")
			self.assertIn("Operator alerts reach nobody", billing_run_coverage._setup_message())


class TestTaxProfileCheck(IntegrationTestCase):
	def test_a_billed_team_with_no_tax_profile_is_named(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		frappe.db.set_value("Subscription", subscription, "enabled", 1)
		frappe.db.delete("Tax Profile", {"team": TEAM})

		self.assertIn(TEAM, [v.team for v in readiness.check_billed_teams_have_a_tax_profile()])


class TestBillingActivity(IntegrationTestCase):
	def test_a_failure_can_be_found_by_its_flow_and_outcome(self):
		make_plan(PLAN)
		subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(subscription, "Created", 1000, "2026-06-01 00:00:00")
		with patch(RATE, side_effect=frappe.ValidationError("No rate for Storage")):
			run.draft_team_invoice(TEAM, *PERIOD)

		_, rows, *_rest = billing_activity.execute({"team": TEAM, "category": "Invoice", "outcome": "Failed"})

		self.assertEqual([row.reason for row in rows], ["No rate for Storage"])

	def test_the_writer_states_the_outcome_and_a_move_to_failed_is_a_failure(self):
		attempt = frappe.get_doc(
			{"doctype": "Payment Attempt", "name": "PA-run-outcome", "team": TEAM, "status": "Initiated"}
		)
		transition(attempt, "Failed")
		record_team_event(TEAM, "Invoice Retry Failed Over", "Invoice")

		outcomes = dict(
			frappe.get_all(
				"Billing Event", filters={"team": TEAM}, fields=["event_type", "outcome"], as_list=True
			)
		)
		self.assertEqual(
			outcomes, {"Payment Attempt Failed": "Failed", "Invoice Retry Failed Over": "Success"}
		)

	def test_a_new_subscription_is_in_the_activity(self):
		make_plan(PLAN)
		make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")

		_, rows, *_rest = billing_activity.execute({"team": TEAM, "category": "Subscription"})

		self.assertIn("Subscription Created", [row.event_type for row in rows])
