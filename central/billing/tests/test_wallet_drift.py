# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A wallet whose balance no ledger entry explains stops every money movement on it."""

import frappe

from central.billing.revenue import credits
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-wallet-drift"


class TestWalletDrift(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		credits.grant_promotional_credits(TEAM, 1000, "INR", note="Welcome credits")

	def _drift(self, balance=3500):
		frappe.db.set_value("Credit Wallet", credits.wallet_name(TEAM, "INR"), "balance", balance)

	def test_a_wallet_balance_cannot_be_edited(self):
		wallet = frappe.get_doc("Credit Wallet", credits.wallet_name(TEAM, "INR"))
		wallet.balance = 5000
		with self.assertRaises(frappe.ValidationError):
			wallet.save(ignore_permissions=True)

	def test_a_wallet_cannot_start_with_a_balance(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Credit Wallet", "team": TEAM, "currency": "USD", "balance": 25}
			).insert(ignore_permissions=True)

	def test_drifted_wallet_refuses_a_debit(self):
		self._drift()
		with self.assertRaises(credits.WalletDrift):
			credits.apply_credit(TEAM, 100, "INR", reference_type="Invoice", reference_name="INV-1")

	def test_drifted_wallet_refuses_a_credit(self):
		self._drift()
		with self.assertRaises(credits.WalletDrift):
			credits.grant_promotional_credits(TEAM, 100, "INR")

	def test_drifted_wallet_refuses_provisioning_against_it(self):
		self._drift()
		with self.assertRaises(credits.WalletDrift):
			credits.lock_team_wallet(TEAM, "INR")

	def test_wallet_that_matches_its_ledger_moves_money(self):
		credits.apply_credit(TEAM, 100, "INR", reference_type="Invoice", reference_name="INV-1")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 900)
