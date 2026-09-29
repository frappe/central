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
