# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Wallet top-ups become advances with GST included, and how GST applies to a team."""

from unittest.mock import patch

import frappe

from central.billing.ingester import advance, gst
from central.billing.revenue import credits
from central.billing.tests.accounting_fake import (
	COMPANY_GSTIN,
	IN_STATE,
	OUT_STATE,
	FakeAccountingSystem,
	billing_team,
	configure_accounting,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-advance"
GSTIN = "27AABCT1111T1Z5"


class AdvanceTestCase(IntegrationTestCase):
	def setUp(self):
		conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		conf.start()
		self.addCleanup(conf.stop)
		configure_accounting()
		self.remote = FakeAccountingSystem()
		self.enterContext(self.remote.patches())

	def _top_up(self, amount=10000, currency="INR", payment_id="pi_topup_1"):
		with patch("central.billing.ingester.advance.enqueue_sync") as enqueue:
			entry = credits.purchase(TEAM, amount, currency, gateway_payment_id=payment_id, gateway="Stripe")[
				"ledger_entry"
			]
		return entry, enqueue


class TestTopUp(AdvanceTestCase):
	def test_a_top_up_queues_its_advance(self):
		billing_team(TEAM, gstin=GSTIN)
		entry, enqueue = self._top_up()
		enqueue.assert_called_once_with(entry)

	def test_gst_is_paid_on_top_and_kept_beside_the_credit(self):
		billing_team(TEAM, gstin=GSTIN)
		entry, _ = self._top_up(amount=11800)
		row = frappe.db.get_value("Credit Ledger Entry", entry, ["amount", "tax_amount"], as_dict=True)
		self.assertEqual((row.amount, row.tax_amount), (10000, 1800))
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 10000)
		self.assertEqual(credits.advance_gst_balance(TEAM, "INR"), 1800)

	def test_an_overseas_top_up_is_all_credit(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		entry, _ = self._top_up(amount=500, currency="USD")
		self.assertEqual(frappe.db.get_value("Credit Ledger Entry", entry, "tax_amount"), 0)

	def test_the_advance_books_the_credit_and_its_gst(self):
		billing_team(TEAM, gstin=GSTIN)
		entry, _ = self._top_up(amount=11800)
		name = advance.sync_advance(entry)

		payment = self.remote.posts("Payment Entry")[-1]
		self.assertEqual(payment["docstatus"], 1)
		self.assertEqual(payment["naming_series"], "RV/.TFY./.######")
		self.assertEqual(payment["paid_from"], "Customer Advances - TC")
		self.assertEqual(payment["paid_to"], "Stripe Clearing INR - TC")
		self.assertEqual(payment["reference_no"], "pi_topup_1")
		self.assertEqual(payment["company_gstin"], COMPANY_GSTIN)
		self.assertEqual(payment["place_of_supply"], "27-Maharashtra")
		taxes = payment["taxes"]
		self.assertTrue(
			all(t["included_in_paid_amount"] and t["charge_type"] == "On Paid Amount" for t in taxes)
		)
		self.assertEqual(payment["paid_amount"], 11800)
		self.assertEqual([t["tax_amount"] for t in taxes], [900, 900])
		self.assertEqual(frappe.db.get_value("Credit Ledger Entry", entry, "advance_id"), name)

	def test_an_advance_already_booked_is_adopted(self):
		billing_team(TEAM, gstin=GSTIN)
		entry, _ = self._top_up()
		self.remote.records[("Payment Entry", "RV-OLD")] = {"reference_no": "pi_topup_1"}
		self.assertEqual(advance.sync_advance(entry), "RV-OLD")
		self.assertEqual(self.remote.posted, [])

	def test_an_overseas_advance_has_no_gst(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		entry, _ = self._top_up(amount=500, currency="USD")
		advance.sync_advance(entry)
		payment = self.remote.posts("Payment Entry")[-1]
		self.assertEqual(payment["taxes"], [])
		self.assertEqual(payment["paid_to"], "Stripe Clearing USD - TC")

	def test_waits_for_the_customer(self):
		billing_team(TEAM, gstin=GSTIN)
		frappe.db.set_value("Billing Profile", TEAM, "profile_id", None)
		entry, _ = self._top_up()
		with patch("central.billing.ingester.customer._enqueue"), self.assertRaises(frappe.ValidationError):
			advance.sync_advance(entry)
		self.assertEqual(self.remote.posted, [])

	def test_a_gateway_with_no_accounts_is_refused(self):
		billing_team(TEAM, gstin=GSTIN)
		with patch("central.billing.ingester.advance.enqueue_sync"):
			entry = credits.purchase(TEAM, 100, "INR", gateway_payment_id="pay_1", gateway="Razorpay")[
				"ledger_entry"
			]
		with self.assertRaises(frappe.ValidationError):
			advance.sync_advance(entry)

	def test_nothing_is_queued_while_sync_is_off(self):
		frappe.local.conf["enable_erpnext_sync"] = 0
		with patch("frappe.enqueue") as enqueue:
			advance.enqueue_sync("any")
		enqueue.assert_not_called()

	def test_the_daily_retry_queues_what_never_synced(self):
		billing_team(TEAM, gstin=GSTIN)
		entry, _ = self._top_up()
		with patch("central.billing.ingester.advance.enqueue_sync") as enqueue:
			advance.sync_pending_advances()
		self.assertIn(entry, [c.args[0] for c in enqueue.call_args_list])


class TestGstTreatment(AdvanceTestCase):
	def test_same_state_registered(self):
		billing_team(TEAM, gstin=GSTIN)
		t = gst.treatment(TEAM)
		self.assertEqual((t.gstin, t.gst_category, t.template), (GSTIN, "Registered Regular", IN_STATE))

	def test_other_state_unregistered(self):
		billing_team(TEAM, state="Karnataka")
		t = gst.treatment(TEAM)
		self.assertEqual(
			(t.gst_category, t.place_of_supply, t.template), ("Unregistered", "29-Karnataka", OUT_STATE)
		)

	def test_lapsed_gstin_is_unregistered(self):
		billing_team(TEAM, gstin=GSTIN)
		frappe.db.set_value("Billing Profile", TEAM, "gst_status", "Cancelled")
		self.assertEqual(gst.treatment(TEAM).gst_category, "Unregistered")

	def test_sez_is_zero_rated(self):
		billing_team(TEAM, gstin=GSTIN)
		frappe.db.set_value("Tax Profile", TEAM, {"zero_rated": 1, "zero_rating_reason": "SEZ"})
		t = gst.treatment(TEAM)
		self.assertEqual((t.gst_category, t.template), ("SEZ", None))

	def test_overseas(self):
		billing_team(TEAM, country="United States", state="California", currency="USD")
		t = gst.treatment(TEAM)
		self.assertEqual(
			(t.gst_category, t.place_of_supply, t.template), ("Overseas", "96-Other Countries", None)
		)
