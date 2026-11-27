# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A reissue gives back the corrections its invoice billed, so the replacement bills the true day."""

from central.billing.platform import readiness
from central.billing.revenue import usage_corrections
from central.billing.tests.test_usage_corrections import MONTH_TEAM, OneMonthFixture, credit_due_rows
from central.billing.tests.utils import BillingTestCase


def reissued_rows(month_row: str) -> list:
	return [violation for violation in readiness.CHECKS["M7"][1]() if violation.subject == month_row]


class TestReleasedCorrections(OneMonthFixture, BillingTestCase):
	def bill_a_rise_on_invoice_x_then_a_drop(self) -> None:
		"""Day 10 billed 10, then 12 billed on invoice X, then 11 rated Credit Due against the 12."""
		self.bill({10: 10, 11: 10})
		self.correct(10, 12, hour=18)
		usage_corrections.stamp(usage_corrections.rate_open(MONTH_TEAM), "invoice-x", MONTH_TEAM)
		self.correct(10, 11, hour=20)
		usage_corrections.rate_open(MONTH_TEAM)

	def statuses(self) -> list:
		return [(c.value, c.status, c.invoice) for c in self.corrections()]

	def test_a_plain_reissue_bills_the_correction_again(self):
		self.bill({10: 10, 11: 10})
		self.correct(10, 12, hour=18)
		usage_corrections.stamp(usage_corrections.rate_open(MONTH_TEAM), "invoice-x", MONTH_TEAM)

		usage_corrections.release("invoice-x", MONTH_TEAM)
		rated = usage_corrections.rate_open(MONTH_TEAM)

		self.assertEqual([line["quantity"] for line in rated.lines], [2])
		self.assertEqual(self.statuses(), [(12, "Open", None)])

	def test_a_reissue_under_a_later_drop_bills_the_true_day(self):
		self.bill_a_rise_on_invoice_x_then_a_drop()

		usage_corrections.release("invoice-x", MONTH_TEAM)
		rated = usage_corrections.rate_open(MONTH_TEAM)

		# X is gone, so the 12 is written off and the 11 bills its rise over the 10 still billed.
		self.assertEqual(self.statuses(), [(12, "Written Off", None), (11, "Open", None)])
		self.assertEqual([line["quantity"] for line in rated.lines], [1])
		self.assertEqual(credit_due_rows(self.month_row), [])
		self.assertEqual(reissued_rows(self.month_row), [])
		self.assertEqual(10 + sum(line["quantity"] for line in rated.lines), 11)

	def test_a_reissue_never_reopens_a_credited_later_value(self):
		self.bill_a_rise_on_invoice_x_then_a_drop()
		credited = self.corrections()[1].name
		usage_corrections.mark_credited(credited, "credit note CN-1")

		usage_corrections.release("invoice-x", MONTH_TEAM)

		self.assertEqual(self.statuses(), [(12, "Written Off", "invoice-x"), (11, "Credited", None)])
		self.assertEqual(usage_corrections.rate_open(MONTH_TEAM).lines, [])
		[violation] = reissued_rows(self.month_row)
		self.assertIn("invoice-x", violation.detail)
		self.assertIn("Bill the 2.0 it added by hand", violation.detail)

	def test_a_reissue_under_a_later_billed_value_leaves_it_for_an_operator(self):
		self.bill({10: 10, 11: 10})
		self.correct(10, 12, hour=18)
		usage_corrections.stamp(usage_corrections.rate_open(MONTH_TEAM), "invoice-x", MONTH_TEAM)
		self.correct(10, 13, hour=20)
		usage_corrections.stamp(usage_corrections.rate_open(MONTH_TEAM), "invoice-y", MONTH_TEAM)

		usage_corrections.release("invoice-x", MONTH_TEAM)

		self.assertEqual(self.statuses(), [(12, "Written Off", "invoice-x"), (13, "Billed", "invoice-y")])
		self.assertEqual(len(reissued_rows(self.month_row)), 1)

	def test_a_second_reissue_gives_back_every_value_it_billed(self):
		self.bill_a_rise_on_invoice_x_then_a_drop()
		self.correct(10, 13, hour=22)
		usage_corrections.release("invoice-x", MONTH_TEAM)
		billed = usage_corrections.rate_open(MONTH_TEAM)
		usage_corrections.stamp(billed, "invoice-x2", MONTH_TEAM)

		usage_corrections.release("invoice-x2", MONTH_TEAM)
		reissued = usage_corrections.rate_open(MONTH_TEAM)

		self.assertEqual([line["quantity"] for line in billed.lines], [1, 2])
		self.assertEqual(reissued.lines, billed.lines)
		self.assertEqual(self.statuses(), [(12, "Written Off", None), (11, "Open", None), (13, "Open", None)])
