# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from central.billing.catalog.pricing import resolve_rate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def _rows(*triples):
	# (cluster, currency, rate)
	return [frappe._dict(cluster=c, currency=cur, rate=r) for c, cur, r in triples]


import frappe  # noqa: E402


class TestResolveRate(IntegrationTestCase):
	def test_global_rate_for_currency(self):
		rows = _rows(("", "USD", 40), ("", "INR", 3200))
		self.assertEqual(resolve_rate(rows, "USD"), 40)
		self.assertEqual(resolve_rate(rows, "INR"), 3200)

	def test_regional_override_wins_over_global(self):
		rows = _rows(("", "INR", 3200), ("ap-south-1", "INR", 3500))
		self.assertEqual(resolve_rate(rows, "INR", cluster="ap-south-1"), 3500)

	def test_falls_back_to_global_when_no_regional_row(self):
		rows = _rows(("", "INR", 3200), ("ap-south-1", "INR", 3500))
		self.assertEqual(resolve_rate(rows, "INR", cluster="us-east-1"), 3200)

	def test_missing_currency_returns_none(self):
		rows = _rows(("", "USD", 40))
		self.assertIsNone(resolve_rate(rows, "EUR"))
