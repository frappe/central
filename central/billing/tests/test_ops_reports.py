# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The operational reports: webhook lag, dunning recovery, involuntary churn."""

import frappe

from central.billing.report.dunning_recovery import dunning_recovery
from central.billing.report.gateway_payment_success_ratio import gateway_payment_success_ratio
from central.billing.report.involuntary_churn import involuntary_churn
from central.billing.report.webhook_lag import webhook_lag
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, ensure_team

MONTH = "2026-06"


def _event(subject_doctype, subject, from_state, to_state, day="2026-06-10"):
	frappe.get_doc(
		{
			"doctype": "Billing Event",
			"occurred_at": f"{day} 10:00:00",
			"event_type": f"{subject_doctype} {to_state}",
			"subject_doctype": subject_doctype,
			"subject": subject,
			"from_state": from_state,
			"to_state": to_state,
		}
	).insert(ignore_permissions=True)


def _row(rows, month=MONTH):
	return next(r for r in rows if r["month"] == month)


class TestWebhookLag(BillingTestCase):
	def setUp(self):
		self.gateway = make_stripe_gateway("GW-Lag-Stripe").name

	def _webhook(self, received, processed):
		event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": frappe.generate_hash(length=10),
				"event_type": "payment_intent.succeeded",
				"status": "Processed",
				"processed_at": processed,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Webhook Event", event.name, "creation", received, update_modified=False)
		return event.name

	def test_lag_is_measured_from_receipt_to_processing(self):
		self._webhook("2026-06-10 10:00:00", "2026-06-10 10:00:05")
		_columns, rows, _msg, _chart, summary = webhook_lag.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30", "gateway": self.gateway}
		)
		self.assertEqual(rows[0]["events"], 1)
		self.assertEqual(rows[0]["worst_seconds"], 5.0)
		self.assertEqual(summary[0]["value"], 1)

	def test_an_event_over_the_threshold_is_counted_as_slow(self):
		self._webhook("2026-06-10 10:00:00", "2026-06-10 10:00:02")
		self._webhook("2026-06-10 11:00:00", "2026-06-10 11:05:00")
		_columns, rows, _msg, _chart, _summary = webhook_lag.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30", "gateway": self.gateway}
		)
		self.assertEqual(rows[0]["events"], 2)
		self.assertEqual(rows[0]["slow"], 1)

	def test_an_unprocessed_webhook_has_no_lag_to_report(self):
		frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": frappe.generate_hash(length=10),
				"event_type": "payment_intent.succeeded",
				"status": "Received",
			}
		).insert(ignore_permissions=True)
		_columns, rows, _msg, _chart, _summary = webhook_lag.execute({"gateway": self.gateway})
		self.assertEqual(rows, [])


class TestDunningRecovery(BillingTestCase):
	def test_an_invoice_that_went_overdue_then_paid_counts_as_recovered(self):
		_event("Invoice", "INV-A", "Open", "Overdue")
		_event("Invoice", "INV-A", "Overdue", "Paid", day="2026-06-20")
		_event("Invoice", "INV-B", "Open", "Overdue")

		_columns, rows, _msg, _chart, _summary = dunning_recovery.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30"}
		)
		row = _row(rows)
		self.assertEqual(row["went_overdue"], 2)
		self.assertEqual(row["recovered"], 1)
		self.assertEqual(row["still_owed"], 1)
		self.assertEqual(row["recovery_rate"], 50.0)

	def test_an_invoice_paid_without_going_overdue_is_not_in_the_denominator(self):
		_event("Invoice", "INV-C", "Open", "Paid")
		_columns, rows, _msg, _chart, _summary = dunning_recovery.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30"}
		)
		self.assertEqual(rows, [])

	def test_a_recovery_after_the_window_still_counts(self):
		_event("Invoice", "INV-D", "Open", "Overdue", day="2026-06-28")
		_event("Invoice", "INV-D", "Overdue", "Paid", day="2026-07-03")
		_columns, rows, _msg, _chart, _summary = dunning_recovery.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30"}
		)
		# The window selects who entered dunning; being paid in July is still a recovery.
		self.assertEqual({r["month"] for r in rows}, {MONTH})
		self.assertEqual(_row(rows)["recovered"], 1)


class TestGatewayAuthRateOverTime(BillingTestCase):
	def setUp(self):
		self.gateway = make_stripe_gateway("GW-Trend-Stripe").name
		self.team = ensure_team("team-authrate")
		self.invoice = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": self.team,
					"status": "Open",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "USD",
					"subtotal": 100,
					"total": 100,
					"expected_collection": 100,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _attempt(self, status, when):
		# Each attempt needs its own retry number: the idempotency key is derived from
		# (invoice, retry_number), so two attempts sharing both would be the same charge.
		self.retry = getattr(self, "retry", 0) + 1
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": self.invoice,
				"gateway": self.gateway,
				"amount": 100,
				"currency": "USD",
				"status": status,
				"retry_number": self.retry,
				"initiated_at": when,
			}
		).insert(ignore_permissions=True)

	def test_success_rate_is_reported_per_month(self):
		self._attempt("Captured", "2026-05-10 10:00:00")
		self._attempt("Failed", "2026-05-11 10:00:00")
		self._attempt("Captured", "2026-06-10 10:00:00")

		_columns, rows, _msg, chart, _summary = gateway_payment_success_ratio.execute(
			{"group_by": "Month", "from_date": "2026-05-01", "to_date": "2026-06-30", "gateway": self.gateway}
		)
		by_month = {r["month"]: r for r in rows}
		self.assertEqual(by_month["2026-05"]["success_rate"], 50.0)
		self.assertEqual(by_month["2026-06"]["success_rate"], 100.0)
		self.assertEqual(chart["data"]["labels"], ["2026-05", "2026-06"])


class TestInvoluntaryChurn(BillingTestCase):
	def test_a_suspension_is_churn_and_a_return_to_current_is_a_save(self):
		_event("Subscription", "SUB-A", "Current", "Past Due")
		_event("Subscription", "SUB-A", "Past Due", "Suspended", day="2026-06-15")
		_event("Subscription", "SUB-B", "Current", "Past Due")
		_event("Subscription", "SUB-B", "Past Due", "Current", day="2026-06-12")

		_columns, rows, _msg, _chart, _summary = involuntary_churn.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30"}
		)
		row = _row(rows)
		self.assertEqual(row["fell_behind"], 2)
		self.assertEqual(row["suspended"], 1)
		self.assertEqual(row["recovered"], 1)
		self.assertEqual(row["churn_rate"], 50.0)

	def test_a_brand_new_subscription_reaching_current_is_not_a_recovery(self):
		_event("Subscription", "SUB-C", None, "Current")
		_columns, rows, _msg, _chart, _summary = involuntary_churn.execute(
			{"from_date": "2026-06-01", "to_date": "2026-06-30"}
		)
		self.assertEqual(_row(rows)["recovered"], 0)
