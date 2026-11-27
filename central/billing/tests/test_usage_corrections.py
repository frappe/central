# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A later value for a billed day is billed on the next invoice at the terms of the month that billed it."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.platform import alerts, readiness
from central.billing.revenue import usage_corrections, usage_month
from central.billing.revenue.invoicing import generate
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.invoicing.lifecycle import reissue_invoice
from central.billing.tests.test_ai_billing import TEAM_INR, AIBillingCase, feed, forget_rate_readings, rate_on
from central.billing.tests.test_bundled_buckets import TEAM
from central.billing.tests.test_usage_month_invoicing import (
	JULY_PERIOD,
	JUNE_PERIOD,
	TEAM_BUCKET,
	StorageMonthsFixture,
)
from central.billing.tests.utils import BillingTestCase, ensure_team, usage_days

AUGUST_PERIOD = ("2026-08-01", "2026-08-31")
MONTH_TEAM = "team-correction-month"
MONTH_SUBJECT = "correction-month-subject"
MONTH_INVOICE = "correction-month-invoice"


def credit_due_rows(month_row: str) -> list:
	return [violation for violation in readiness.CHECKS["M4"][1]() if violation.subject == month_row]


class TestStorageCorrections(StorageMonthsFixture, BillingTestCase):
	"""30 GB in the team bucket all June, at 2.5 a GB-month with no allowance."""

	def setUp(self):
		self.set_up_storage_months()
		self.read_june()
		self.june = generate_team_invoice(TEAM, *JUNE_PERIOD)

	def correction(self, subject: str = TEAM_BUCKET, day: str = "2026-06-30"):
		[row] = usage_days(subject=subject, day=day)
		[correction] = frappe.get_doc("Usage Month", row.month_row).corrections
		return correction, row

	def lines(self, invoice: str) -> list:
		return frappe.get_all(
			"Invoice Line Item",
			filters={"parent": invoice, "resource_type": "Storage"},
			fields=["subscription_resource", "description", "quantity", "rate", "amount"],
			order_by="description asc",
		)

	def draft(self, period) -> str:
		self.read_team_bucket(period[0], 31)
		return generate_team_invoice(TEAM, *period)

	def test_a_higher_value_is_billed_on_the_next_invoice_at_the_months_rate(self):
		june_total = frappe.db.get_value("Invoice", self.june, "total")
		self.read_team_bucket("2026-06-30", 60)
		correction, row = self.correction()

		july = self.draft(JULY_PERIOD)

		self.assertEqual(frappe.db.get_value("Invoice", self.june, "total"), june_total)
		# The month's own line has no description; the correction's names the day and both reports.
		[own, adjustment] = self.lines(july)
		# 30 GB more for 1 of June's 30 days is 1 GB-month at June's 2.5; July's own day is 31 GB for 1 of 31.
		self.assertEqual((adjustment.quantity, adjustment.rate, adjustment.amount), (1.0, 2.5, 2.5))
		self.assertEqual(
			adjustment.description,
			f"Correction · {TEAM_BUCKET} · 30 Jun 2026 · report {row.report} → {correction.report}",
		)
		self.assertNotEqual(correction.original_report, correction.report)
		self.assertEqual(correction.original_report, row.report)
		self.assertEqual(own.amount, 2.5)
		correction.reload()
		self.assertEqual((correction.status, correction.invoice), ("Billed", july))

	def test_a_reissued_invoice_bills_the_correction_again(self):
		self.read_team_bucket("2026-06-30", 60)
		july = self.draft(JULY_PERIOD)

		reissued = reissue_invoice(july, reason="test")

		self.assertIn(2.5, [line.amount for line in self.lines(reissued) if "Correction" in line.description])
		correction, _row = self.correction()
		self.assertEqual((correction.status, correction.invoice), ("Billed", reissued))

	def test_a_billed_correction_is_never_billed_again(self):
		self.read_team_bucket("2026-06-30", 60)
		self.draft(JULY_PERIOD)

		august = self.draft(AUGUST_PERIOD)

		self.assertFalse([line for line in self.lines(august) if "Correction" in line.description])

	def test_a_higher_value_inside_the_bundle_closes_with_no_charge(self):
		# 120 GB on the 30th is still inside the 200 GB the resized plan includes.
		self.read("2026-06-30", 120)
		correction, row = self.correction(subject=self.bucket)
		self.assertEqual(correction.status, "Open")

		july = self.draft(JULY_PERIOD)

		correction.reload()
		self.assertEqual((correction.status, correction.billable_delta), ("No Charge", 0))
		self.assertFalse([line for line in self.lines(july) if "Correction" in line.description])
		self.assertEqual(credit_due_rows(row.month_row), [])
		notes = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Usage Month", "reference_name": row.month_row},
			pluck="content",
		)
		self.assertTrue(any("needs no invoice line" in note for note in notes))
		# A closed correction is never replaced; a later value is a new one against the billed value.
		self.read("2026-06-30", 300)
		corrections = frappe.get_doc("Usage Month", row.month_row).corrections
		# A value rated as no change is what the day bills now, so the next one is weighed against it.
		self.assertEqual(
			[(c.status, c.billed_value, c.value) for c in corrections],
			[("No Charge", correction.billed_value, 120), ("Open", 120, 300)],
		)

	def test_a_month_below_the_minimum_keeps_the_correction_open(self):
		self.read_team_bucket("2026-06-30", 60)
		with patch.object(generate.settings, "minimum_invoice_amount", return_value=1_000_000):
			self.assertIsNone(self.draft(JULY_PERIOD))

		correction, _row = self.correction()
		self.assertEqual((correction.status, correction.invoice), ("Open", None))

	def test_a_correction_past_its_window_is_written_off_with_a_note(self):
		self.read_team_bucket("2026-06-30", 60)
		correction, row = self.correction()
		ended = frappe.utils.getdate() - datetime.timedelta(days=usage_corrections.WINDOW_DAYS + 1)
		frappe.db.set_value("Usage Month Correction", correction.name, "billed_invoice_date", ended)

		self.assertEqual(usage_corrections.write_off_expired(), 1)

		correction.reload()
		self.assertEqual(correction.status, "Written Off")
		notes = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Usage Month", "reference_name": row.month_row},
			pluck="content",
		)
		self.assertTrue(any("written off" in note for note in notes))
		july = self.draft(JULY_PERIOD)
		self.assertFalse([line for line in self.lines(july) if "Correction" in line.description])


class TestAICorrections(AIBillingCase):
	"""2 USD of one model on 10 June, billed at June's 84.1."""

	def setUp(self):
		super().setUp()
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0})
		self.read("2026-06-10")
		with feed(rate_on("2026-06-01", 84.1)):
			self.invoice_lines(TEAM_INR)

	def read_later(self, day: str, cost: float) -> None:
		"""Read a day again an hour later, so its value is the newer one."""
		self.land(TEAM_INR, day, {"gpt-4o": cost})
		later = frappe.utils.now_datetime() + datetime.timedelta(hours=1)
		with patch("frappe.utils.now_datetime", return_value=later):
			self.read(day)

	def july_lines(self) -> list:
		self.land(TEAM_INR, "2026-07-05", {"gpt-4o": 1.0})
		self.read("2026-07-05")
		forget_rate_readings()
		with feed(rate_on("2026-07-01", 85.0)):
			return self.invoice_lines(TEAM_INR, JULY_PERIOD)

	def correction(self):
		[row] = self.days(TEAM_INR, day=frappe.utils.getdate("2026-06-10"))
		[correction] = frappe.get_doc("Usage Month", row.month_row).corrections
		return correction, row

	def test_an_inr_correction_bills_at_the_rate_of_the_month_it_corrects(self):
		self.read_later("2026-06-10", 3.0)

		# One more USD for 10 June at June's 84.1; July's own USD at July's 85.
		self.assertEqual(sorted(line.amount for line in self.july_lines()), [84.1, 85.0])

	def test_a_lower_value_is_credit_due_and_raises_a_readiness_row(self):
		self.read_later("2026-06-10", 1.5)
		correction, row = self.correction()
		self.assertEqual(correction.status, "Open")
		self.assertEqual(credit_due_rows(row.month_row), [])

		self.assertEqual([line.amount for line in self.july_lines()], [85.0])
		correction.reload()
		self.assertEqual((correction.status, correction.billable_delta), ("Credit Due", -0.5))
		[violation] = credit_due_rows(row.month_row)
		self.assertEqual(violation.team, TEAM_INR)
		self.assertIn(correction.name, violation.detail)
		gaps = [
			a for a in alerts.readiness_gaps() if a.get("check") == "M4" and a["subject"] == row.month_row
		]
		self.assertEqual(len(gaps), 1)

		usage_corrections.mark_credited(correction.name, "credit note CN-1")
		self.assertEqual(credit_due_rows(row.month_row), [])

	def test_a_lower_value_inside_the_allowance_closes_with_no_charge(self):
		# June's month had 5 USD included, so 2 USD and 1.5 USD both bill nothing.
		[june] = frappe.get_all(
			"Usage Month", filters={"team": TEAM_INR, "counted_at": ["is", "set"]}, pluck="name"
		)
		frappe.db.set_value("Usage Month", june, "locked_allowance", 5)
		self.read_later("2026-06-10", 1.5)
		correction, row = self.correction()

		self.assertEqual([line.amount for line in self.july_lines()], [85.0])

		correction.reload()
		self.assertEqual((correction.status, correction.billable_delta), ("No Charge", 0))
		self.assertEqual(credit_due_rows(row.month_row), [])

	def test_a_lower_value_past_the_window_is_still_credit_due(self):
		self.read_later("2026-06-10", 1.5)
		correction, row = self.correction()
		ended = frappe.utils.getdate() - datetime.timedelta(days=120)
		frappe.db.set_value("Usage Month Correction", correction.name, "billed_invoice_date", ended)

		self.assertEqual(usage_corrections.write_off_expired(), 0)
		self.assertEqual([line.amount for line in self.july_lines()], [85.0])

		correction.reload()
		self.assertEqual(correction.status, "Credit Due")
		[violation] = credit_due_rows(row.month_row)
		self.assertIn(correction.name, violation.detail)


def sum_line(day: int, quantity: float, hour: int = 12, included: float = 0) -> dict:
	bundle = {"included": included} if included else {}
	return {
		"service": "storage",
		"meter": "bytes_stored",
		"subject": MONTH_SUBJECT,
		"dimension": "",
		"day": datetime.date(2026, 6, day),
		"aggregation": "Sum",
		"team": MONTH_TEAM,
		"subscription": "correction-month-subscription",
		"resource_type": "Storage",
		"unit": "GB",
		"quantity": quantity,
		"as_of": datetime.datetime(2026, 6, day, hour),
		**bundle,
	}


class TestCorrectionsOfOneMonth(BillingTestCase):
	"""June's Sum days billed by one invoice at 1 a unit, corrected later."""

	def setUp(self):
		ensure_team(MONTH_TEAM)

	def bill(self, quantities: dict[int, float], included: float = 0, allowance: float = 0) -> None:
		lines = [sum_line(day, quantity, included=included) for day, quantity in quantities.items()]
		usage_month.write_lines(lines, "report-1", "Pushed")
		self.month_row = frappe.db.get_value("Usage Month", {"subject": MONTH_SUBJECT})
		usage_month.stamp_days(
			{self.month_row: sum(usage_month.bit(day) for day in quantities)}, MONTH_INVOICE
		)
		terms = {"locked_allowance": allowance, "locked_rate": 1, "currency": "USD"}
		frappe.db.set_value(
			"Usage Month",
			self.month_row,
			{
				**terms,
				"invoice": MONTH_INVOICE,
				"counted_at": frappe.utils.now_datetime(),
				"quantity": sum(quantities.values()),
				"resource_id": MONTH_SUBJECT,
			},
		)

	def correct(self, day: int, quantity: float, hour: int) -> None:
		usage_month.write_lines([sum_line(day, quantity, hour=hour)], f"report-{hour}", "Pushed")
		# No Invoice row backs the test invoice, so the window starts today.
		frappe.db.set_value(
			"Usage Month Correction",
			{"parent": self.month_row, "billed_invoice_date": ["is", "not set"]},
			"billed_invoice_date",
			frappe.utils.getdate(),
		)

	def corrections(self) -> list:
		return frappe.get_doc("Usage Month", self.month_row).corrections

	def test_a_resend_of_a_credited_value_adds_no_correction(self):
		self.bill({10: 10, 11: 10})
		self.correct(10, 5, hour=18)
		usage_corrections.rate_open(MONTH_TEAM)
		[correction] = self.corrections()
		self.assertEqual((correction.status, correction.billable_delta), ("Credit Due", -5))
		usage_corrections.mark_credited(correction.name, "credit note CN-1")

		self.correct(10, 5, hour=20)

		self.assertEqual([(c.status, c.value) for c in self.corrections()], [("Credited", 5)])
		self.assertEqual(usage_corrections.rate_open(MONTH_TEAM).lines, [])
		self.assertEqual(credit_due_rows(self.month_row), [])

	def test_a_resend_of_a_value_rated_as_no_change_adds_no_correction(self):
		self.bill({10: 10, 11: 10}, allowance=100)
		self.correct(10, 5, hour=18)
		usage_corrections.rate_open(MONTH_TEAM)
		self.assertEqual([c.status for c in self.corrections()], ["No Charge"])

		self.correct(10, 5, hour=20)

		self.assertEqual([(c.status, c.value) for c in self.corrections()], [("No Charge", 5)])
		self.assertEqual(credit_due_rows(self.month_row), [])

	def test_corrections_of_one_bundled_month_net_to_the_true_month(self):
		# A share of 100 over June's 30 days, 120 billed: 20 above it. Day 10 drops 30, day 20 adds 15.
		self.bill({day: {10: 33}.get(day, 3) for day in range(1, 31)}, included=100)
		self.correct(10, 3, hour=18)
		self.correct(20, 18, hour=18)

		rated = usage_corrections.rate_open(MONTH_TEAM)

		# The true month is 105, 5 above the share: the 20 billed above it is owed back and the 5 billed.
		self.assertEqual(
			[(c.day, c.status, c.billable_delta) for c in self.corrections()],
			[(10, "Credit Due", -20), (20, "Open", 5)],
		)
		self.assertEqual([(line["quantity"], line["amount"]) for line in rated.lines], [(5, 5)])

	def test_a_rise_rated_before_a_drop_nets_to_the_true_month_too(self):
		self.bill({day: {20: 33}.get(day, 3) for day in range(1, 31)}, included=100)
		self.correct(10, 18, hour=18)
		self.correct(20, 3, hour=18)

		rated = usage_corrections.rate_open(MONTH_TEAM)

		# 15 billed for day 10 and 30 owed back for day 20: 20 + 15 - 30 is the true month's 5.
		self.assertEqual([line["quantity"] for line in rated.lines], [15])
		self.assertEqual([(c.day, c.billable_delta) for c in self.corrections()], [(10, 15), (20, -30)])

	def test_a_lower_value_after_a_write_off_is_rated_against_the_billed_value(self):
		self.bill({10: 10})
		self.correct(10, 15, hour=18)
		ended = frappe.utils.getdate() - datetime.timedelta(days=usage_corrections.WINDOW_DAYS + 1)
		frappe.db.set_value(
			"Usage Month Correction", {"parent": self.month_row}, "billed_invoice_date", ended
		)
		self.assertEqual(usage_corrections.write_off_expired(), 1)

		self.correct(10, 6, hour=20)
		usage_corrections.rate_open(MONTH_TEAM)

		self.assertEqual(
			[(c.status, c.billed_value, c.value, c.billable_delta) for c in self.corrections()],
			[("Written Off", 10, 15, 0), ("Credit Due", 10, 6, -4)],
		)


class TestLivePricedCorrectionRate(BillingTestCase):
	"""A live-priced month bills a correction at the rate on the month's own invoice line."""

	invoice = "live-rate-invoice"

	def setUp(self):
		live = frappe._dict(name="live-plan", pricing_mode="Live")
		self.enterContext(patch.object(usage_corrections, "metered_plan_for", return_value=live))
		self.enterContext(patch.object(usage_corrections, "get_catalog_rates", return_value=[]))
		self.enterContext(patch.object(usage_corrections, "resolve_rate", return_value=3.0))
		# Child rows are not swept with the tracked doctypes.
		self.addCleanup(frappe.db.delete, "Invoice Line Item", {"parent": self.invoice})
		for description, charge_date, rate in (
			("gpt-4o · 2 USD at 84.1", None, 2.0),
			# A correction line names the day it corrects, and another model has its own line.
			("Correction · gpt-4o · 10 Jun 2026", "2026-06-10", 9.0),
			("claude-sonnet · 1 USD at 84.1", None, 7.0),
		):
			frappe.get_doc(
				{
					"doctype": "Invoice Line Item",
					"parent": self.invoice,
					"parenttype": "Invoice",
					"parentfield": "items",
					"subscription_resource": "live-subject",
					"resource_type": "AI Usage",
					"description": description,
					"charge_date": charge_date,
					"rate": rate,
				}
			).db_insert()

	def rate_of(self, dimension: str) -> float:
		carrier = frappe._dict(
			resource_id="live-subject",
			resource_type="AI Usage",
			dimension=dimension,
			currency="INR",
			cluster=None,
			locked_rate=1.0,
		)
		return usage_corrections._billed_rate(carrier, self.invoice)

	def test_the_rate_is_the_one_on_the_months_own_line_for_its_model(self):
		self.assertEqual(self.rate_of("gpt-4o"), 2.0)
		self.assertEqual(self.rate_of("claude-sonnet"), 7.0)

	def test_a_month_inside_its_allowance_had_no_line_and_takes_todays_rate(self):
		self.assertEqual(self.rate_of("mistral-large"), 3.0)
