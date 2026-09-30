# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An invoice paid from the wallet: top-up credit pays the net, its GST pays the GST."""

from unittest.mock import patch

import frappe

from central.billing.revenue import credits
from central.billing.revenue.invoicing.lifecycle import open_and_collect
from central.billing.tests.accounting_fake import billing_team
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-wallet-draw"


class WalletDrawTestCase(IntegrationTestCase):
	def setUp(self):
		billing_team(TEAM)  # Maharashtra, GST at 18%, no accounting sync in these tests
		for target in (
			"central.billing.ingester.advance.enqueue_sync",
			"central.billing.ingester.erpnext_sync.enqueue_invoice_sync",
			"central.billing.payments.collection.collect_invoice",
		):
			self.enterContext(patch(target))

	def _top_up(self, paid):
		credits.purchase(
			TEAM, paid, "INR", gateway_payment_id=frappe.generate_hash(length=8), gateway="Stripe"
		)

	def _open(self, net, month):
		start = f"2026-{month:02d}-01"
		inv = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Draft",
				"period_start": start,
				"period_end": str(frappe.utils.get_last_day(start)),
				"currency": "INR",
				"subtotal": net,
				"total": net,
				"items": [{"plan": "VM", "rate": net, "amount": net}],
			}
		).insert(ignore_permissions=True)
		open_and_collect(inv.name)
		return frappe.get_doc("Invoice", inv.name)

	def _state(self, inv):
		return (
			inv.credit_applied,
			inv.advance_applied,
			inv.advance_tax_applied,
			inv.expected_collection,
			inv.status,
		)


class TestWalletDraw(WalletDrawTestCase):
	def test_the_top_up_pays_the_invoice_and_its_gst(self):
		self._top_up(11800)  # 10,000 credit + 1,800 GST
		inv = self._open(8000, 8)  # 8,000 + 1,440 GST
		self.assertEqual(self._state(inv), (8000, 8000, 1440, 0, "Paid"))
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)
		self.assertEqual(credits.advance_gst_balance(TEAM, "INR"), 360)

	def test_what_the_wallet_cannot_cover_goes_to_the_card(self):
		self._top_up(11800)
		self._open(8000, 8)
		inv = self._open(5000, 9)  # 5,000 + 900 GST, with 2,000 + 360 left
		self.assertEqual(self._state(inv), (2000, 2000, 360, 3540, "Open"))
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 0)
		self.assertEqual(credits.advance_gst_balance(TEAM, "INR"), 0)

	def test_promotional_credit_pays_gst_included(self):
		credits.grant_promotional_credits(TEAM, 1180, "INR")
		inv = self._open(1000, 8)  # 1,000 + 180 GST
		self.assertEqual(self._state(inv), (1180, 0, 0, 0, "Paid"))

	def test_promotional_credit_is_spent_before_top_up_credit(self):
		credits.grant_promotional_credits(TEAM, 590, "INR")
		self._top_up(11800)
		inv = self._open(1000, 8)  # 1,180: 590 promotional, then 500 + 90 GST from the top-up
		self.assertEqual(self._state(inv), (1090, 500, 90, 0, "Paid"))


class TestCancelUnpaid(WalletDrawTestCase):
	def _cancel(self, inv):
		from central.billing.revenue.invoicing.lifecycle import cancel_invoice

		cancel_invoice(inv.name, reason="wrong plan")
		return frappe.get_doc("Invoice", inv.name)

	def test_credit_and_its_gst_go_back_to_the_wallet(self):
		self._top_up(11800)
		self._open(8000, 8)
		inv = self._open(5000, 9)  # draws 2,000 + 360, waits on the card for the rest
		self.assertEqual(self._cancel(inv).status, "Cancelled")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)
		self.assertEqual(credits.advance_gst_balance(TEAM, "INR"), 360)

	def test_returned_credit_pays_the_next_invoice_with_its_gst(self):
		self._top_up(11800)
		self._open(8000, 8)
		self._cancel(self._open(5000, 9))
		inv = self._open(1000, 10)  # 1,000 + 180 GST, from the returned 2,000 + 360
		self.assertEqual(self._state(inv), (1000, 1000, 180, 0, "Paid"))

	def test_promotional_credit_goes_back_as_promotional(self):
		credits.grant_promotional_credits(TEAM, 590, "INR")
		inv = self._open(1000, 8)  # draws the 590, owes the rest
		self._cancel(inv)
		back = frappe.get_all(
			"Credit Ledger Entry",
			{"team": TEAM, "reference_name": inv.name, "entry_type": "Credit"},
			["amount", "paid_in", "expires_on"],
		)
		expires = credits.promotional_expiry_date()
		self.assertEqual([(b.amount, b.paid_in, b.expires_on) for b in back], [(590, 0, expires)])

	def test_a_paid_invoice_is_refused(self):
		self._top_up(11800)
		inv = self._open(8000, 8)
		with self.assertRaises(frappe.ValidationError):
			self._cancel(inv)

	def test_a_charge_under_way_is_refused(self):
		inv = self._open(1000, 8)
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv.name,
				"team": TEAM,
				"status": "Captured",
				"amount": 1180,
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self._cancel(inv)
