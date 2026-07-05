# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment Method Mix report — payments-via-credits split (Welcome vs Purchased).

Focuses on the fungible-pool attribution: a settlement debit carries no origin, so
applied credit is split in proportion to each team's welcome:purchased funding, per
currency.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.report.payment_method_mix.payment_method_mix import execute
from central.billing.tests.utils import ensure_team

TEAM_A = "team-pmm-a"
TEAM_B = "team-pmm-b"


def _book(team, entry_type, amount, reference_type, currency="INR"):
	frappe.get_doc({
		"doctype": "Credit Ledger Entry",
		"team": team,
		"entry_type": entry_type,
		"amount": amount,
		"currency": currency,
		"reference_type": reference_type,
	}).insert(ignore_permissions=True)


class TestPaymentMethodMixCredits(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM_A)
		ensure_team(TEAM_B)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for team in (TEAM_A, TEAM_B):
			frappe.db.delete("Credit Ledger Entry", {"team": team})

	def _credit_rows(self, filters=None):
		"""Run the report and index the credit rows by (source, currency)."""
		_columns, rows, *_ = execute(filters or {})
		return {
			(r["method_type"], r["currency"]): r
			for r in rows
			if r["method_type"] in ("Welcome Credits", "Purchased Credits")
		}

	def test_applied_credit_split_proportional_to_funding(self):
		# Team A: welcome 100 + purchased 300 (welcome share = 0.25), applies 200.
		_book(TEAM_A, "Credit", 100, "Promotion")
		_book(TEAM_A, "Credit", 300, "Payment Method")
		_book(TEAM_A, "Debit", 200, "Invoice")
		# Team B: welcome-only 100, applies 40 → all welcome.
		_book(TEAM_B, "Credit", 100, "Promotion")
		_book(TEAM_B, "Debit", 40, "Invoice")

		rows = self._credit_rows({"team": None})
		welcome = rows[("Welcome Credits", "INR")]
		purchased = rows[("Purchased Credits", "INR")]

		# 200 × 0.25 (A) + 40 × 1.0 (B) = 50 + 40 = 90 welcome; 200 × 0.75 = 150 purchased.
		self.assertEqual(welcome["credits_applied"], 90.0)
		self.assertEqual(purchased["credits_applied"], 150.0)
		# Team counts: both funded by welcome; only A bought credits.
		self.assertEqual(welcome["total"], 2)
		self.assertEqual(purchased["total"], 1)

	def test_untracked_funding_never_lands_in_welcome(self):
		# Applied credit whose only funding is a refund (not welcome/purchased) must
		# fall to Purchased, so the free-credit figure is never overstated.
		_book(TEAM_A, "Credit", 100, "Refund")
		_book(TEAM_A, "Debit", 60, "Invoice")

		rows = self._credit_rows({"team": TEAM_A})
		self.assertEqual(rows[("Welcome Credits", "INR")]["credits_applied"], 0.0)
		self.assertEqual(rows[("Purchased Credits", "INR")]["credits_applied"], 60.0)

	def test_amounts_split_per_currency(self):
		_book(TEAM_A, "Credit", 100, "Promotion", currency="INR")
		_book(TEAM_A, "Debit", 100, "Invoice", currency="INR")
		_book(TEAM_A, "Credit", 20, "Promotion", currency="USD")
		_book(TEAM_A, "Debit", 20, "Invoice", currency="USD")

		_columns, rows, *_ = execute({"team": TEAM_A})
		# Two currencies present → the money column splits into per-currency columns.
		fieldnames = {c["fieldname"] for c in _columns}
		self.assertIn("credits_applied_inr", fieldnames)
		self.assertIn("credits_applied_usd", fieldnames)

		welcome = {r["currency"]: r for r in rows if r["method_type"] == "Welcome Credits"}
		self.assertEqual(welcome["INR"]["credits_applied_inr"], 100.0)
		self.assertEqual(welcome["USD"]["credits_applied_usd"], 20.0)
