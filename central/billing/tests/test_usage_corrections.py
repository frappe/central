# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A later value for a billed day is billed on the next invoice at the terms of the month that billed it."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.platform import alerts, readiness
from central.billing.revenue import usage_corrections
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
from central.billing.tests.utils import BillingTestCase, usage_days

AUGUST_PERIOD = ("2026-08-01", "2026-08-31")


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
		self.assertEqual(correction.status, "Credit Due")

		self.assertEqual([line.amount for line in self.july_lines()], [85.0])
		[violation] = credit_due_rows(row.month_row)
		self.assertEqual(violation.team, TEAM_INR)
		self.assertIn(correction.name, violation.detail)
		gaps = [
			a for a in alerts.readiness_gaps() if a.get("check") == "M4" and a["subject"] == row.month_row
		]
		self.assertEqual(len(gaps), 1)

		usage_corrections.mark_credited(correction.name, "credit note CN-1")
		self.assertEqual(credit_due_rows(row.month_row), [])
