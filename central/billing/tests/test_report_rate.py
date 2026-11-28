# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Reports turn USD into INR at the rate set by hand, else at the rate kept for the month."""

from unittest.mock import patch

import frappe

from central.billing.report._economics import to_inr
from central.billing.revenue import exchange_rates
from central.billing.tests.utils import BillingTestCase

SET_RATE = "central.billing.revenue.exchange_rates.settings.reporting_usd_to_inr"


def keep(month: str, rate: float) -> None:
	frappe.get_doc(
		{
			"doctype": "Monthly Exchange Rate",
			"month": month,
			"from_currency": "USD",
			"to_currency": "INR",
			"rate": rate,
		}
	).insert(ignore_permissions=True)


class TestReportRate(BillingTestCase):
	def setUp(self):
		super().setUp()
		self.clear_request_cache()
		self.addCleanup(self.clear_request_cache)

	def clear_request_cache(self):
		if getattr(frappe.local, "request_cache", None):
			frappe.local.request_cache.clear()

	def test_the_rate_is_the_set_rate_else_the_nearest_kept_month(self):
		with patch(SET_RATE, return_value=0):
			self.assertEqual(exchange_rates.report_usd_to_inr("2026-09-15"), 0)

		keep("2026-09-01", 90.0)
		keep("2026-11-01", 95.0)
		cases = {
			"the month's own rate": ("2026-11-20", 0, 95.0),
			"the nearest month before": ("2026-10-31", 0, 90.0),
			"the earliest rate, before any was kept": ("2026-06-01", 0, 90.0),
			"the set rate wins": ("2026-11-20", 80.0, 80.0),
		}
		for case, (on, set_rate, expected) in cases.items():
			with self.subTest(case), patch(SET_RATE, return_value=set_rate):
				self.clear_request_cache()
				self.assertEqual(exchange_rates.report_usd_to_inr(on), expected)

	def test_a_billed_month_converts_at_its_own_rate(self):
		keep("2026-09-01", 90.0)
		keep("2026-11-01", 95.0)

		with patch(SET_RATE, return_value=0):
			self.assertEqual(to_inr(10, "USD", "2026-09-01"), 900.0)
			self.assertEqual(to_inr(10, "USD", "2026-11-01"), 950.0)
			self.assertEqual(to_inr(10, "INR", "2026-11-01"), 10.0)

	def test_the_draft_tick_keeps_the_closed_months_rate_and_never_stops_on_a_missing_one(self):
		reading = frappe._dict(rate=95.01, rate_date=frappe.utils.getdate("2026-11-01"), source="rates.test")
		with patch.object(exchange_rates, "feed_rate", return_value=reading):
			exchange_rates.keep_report_rate("2026-11-01")
		self.assertEqual(frappe.db.get_value("Monthly Exchange Rate", {"month": "2026-11-01"}, "rate"), 95.01)

		with patch.object(exchange_rates, "feed_rate", return_value=None):
			exchange_rates.keep_report_rate("2026-08-01")
		self.assertFalse(frappe.db.exists("Monthly Exchange Rate", {"month": "2026-08-01"}))
