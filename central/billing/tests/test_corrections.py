# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Cancelling a paid invoice: a credit note, and each part of the payment given back."""

from unittest.mock import MagicMock, patch

import frappe

from central.billing.gateways.base import RefundResult
from central.billing.ingester.locks import lock_name
from central.billing.payments import corrections
from central.billing.revenue import credits
from central.billing.tests.accounting_fake import (
	FakeAccountingSystem,
	billing_team,
	configure_accounting,
	requires_accounting_system,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

TEAM = "team-corrections"
SALES_INVOICE = "SINV-ORIGINAL"


@requires_accounting_system
class CorrectionsTestCase(IntegrationTestCase):
	def setUp(self):
		conf = patch.dict(frappe.local.conf, {"enable_erpnext_sync": 1})
		conf.start()
		self.addCleanup(conf.stop)
		configure_accounting()
		billing_team(TEAM, gstin="27AABCT1111T1Z5")
		self.remote = FakeAccountingSystem()
		self.enterContext(self.remote.patches())
		self.enterContext(patch("central.billing.payments.corrections._enqueue"))
		self.gateway = MagicMock()
		self.gateway.refund.return_value = RefundResult(
			success=True, status="Completed", gateway_refund_id="re_1", raw={}
		)
		self.enterContext(patch("central.billing.payments.corrections._adapter", return_value=self.gateway))

	def _paid_invoice(self, synced=True, paid_at="2026-09-01 10:00:00"):
		"""5,000 + 900 GST: 2,000 + 360 from the wallet, 3,540 by card."""
		inv = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Paid",
				"period_start": "2026-08-01",
				"period_end": "2026-08-31",
				"currency": "INR",
				"subtotal": 5000,
				"output_tax_amount": 900,
				"total": 5900,
				"credit_applied": 2000,
				"advance_applied": 2000,
				"advance_tax_applied": 360,
				"amount_paid": 3540,
				"paid_at": paid_at,
				"erpnext_invoice": SALES_INVOICE if synced else None,
				"items": [{"plan": "VM", "rate": 5000, "amount": 5000}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv.name,
				"team": TEAM,
				"gateway": "Stripe",
				"currency": "INR",
				"amount": 3540,
				"status": "Captured",
				"gateway_transaction_id": "pi_card",
			}
		).insert(ignore_permissions=True)
		# The top-up this invoice's wallet part came from: 2,000 credit with 360 GST.
		frappe.get_doc(
			{
				"doctype": "Credit Ledger Entry",
				"team": TEAM,
				"entry_type": "Credit",
				"amount": 2000,
				"tax_amount": 360,
				"paid_in": 1,
				"currency": "INR",
			}
		).insert(ignore_permissions=True)
		self.remote.records[("Sales Invoice", SALES_INVOICE)] = {
			"items": [{"item_code": "Cloud Hosting", "rate": 5000, "qty": 1}],
			"taxes": [
				{"account_head": "Output Tax CGST - TC", "rate": 9},
				{"account_head": "Output Tax SGST - TC", "rate": 9},
			],
		}
		return inv.name

	def _run_all(self, invoice):
		for _ in range(10):
			frappe.cache.delete(lock_name(f"cancellation::{invoice}"))
			before = len(self.remote.posted), self._states(invoice)
			corrections.run_cancellation(invoice)
			if (len(self.remote.posted), self._states(invoice)) == before:
				break

	def _states(self, invoice):
		return tuple(
			(r.status, r.payment_record_id, r.advance_id)
			for r in frappe.get_all(
				"Refund", {"invoice": invoice}, ["status", "payment_record_id", "advance_id"]
			)
		)

	def _refund(self, invoice, destination):
		return frappe.get_doc("Refund", {"invoice": invoice, "destination": destination})


class TestCancelAndRefund(CorrectionsTestCase):
	def test_each_part_goes_back_the_way_it_came(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Cancelled")
		self._run_all(inv)

		card = self._refund(inv, "Source")
		self.assertEqual((card.status, card.amount, card.gateway_refund_id), ("Completed", 3540, "re_1"))
		self.assertEqual(self.gateway.refund.call_args.args[3], card.name)  # idempotency key
		self.assertEqual(frappe.db.get_value("Payment Attempt", card.payment_attempt, "status"), "Refunded")

		wallet = self._refund(inv, "Wallet")
		self.assertEqual((wallet.status, wallet.amount), ("Completed", 2360))
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)
		self.assertEqual(credits.advance_gst_balance(TEAM, "INR"), 360)

		self.assertTrue(frappe.db.get_value("Invoice", inv, "credit_note_id"))
		note = self.remote.posts("Sales Invoice")[-1]
		self.assertEqual((note["is_return"], note["return_against"]), (1, SALES_INVOICE))
		self.assertEqual(note["naming_series"], "CN/.TFY./.#####")

		payments = self.remote.posts("Payment Entry")
		card_out = next(p for p in payments if p.get("reference_no") == "re_1")
		self.assertEqual(card_out["paid_from"], "Stripe Clearing INR - TC")
		wallet_out = next(p for p in payments if p.get("reference_no") == wallet.name)
		self.assertEqual(
			(wallet_out["paid_from"], wallet_out["paid_amount"]), ("Wallet Clearing INR - TC", 2360)
		)
		advance = next(p for p in payments if p.get("reference_no") == f"{wallet.name}-advance")
		self.assertEqual(
			(advance["payment_type"], advance["paid_to"]), ("Receive", "Wallet Clearing INR - TC")
		)
		self.assertEqual(sum(t["tax_amount"] for t in advance["taxes"]), 360)
		self.assertEqual(
			frappe.db.get_value(
				"Credit Ledger Entry",
				{"reference_name": inv, "paid_in": 1, "entry_type": "Credit"},
				"advance_id",
			),
			wallet.advance_id,
		)

	def test_running_again_repeats_nothing(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		posted = len(self.remote.posted)
		self._run_all(inv)
		self.assertEqual(len(self.remote.posted), posted)
		self.assertEqual(self.gateway.refund.call_count, 1)

	def test_an_invoice_never_issued_there_needs_no_credit_note(self):
		inv = self._paid_invoice(synced=False)
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		self.assertEqual(self.remote.posted, [])
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)

	def test_a_failed_gateway_refund_is_kept_for_a_person(self):
		self.gateway.refund.return_value = RefundResult(
			success=False, status="failed", gateway_refund_id=None, raw={}
		)
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		self.assertEqual(self._refund(inv, "Source").status, "Failed")
		self.assertEqual(self._refund(inv, "Source").payment_record_id, None)


class TestDispute(CorrectionsTestCase):
	def test_a_lost_dispute_is_not_refunded_again(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(
			inv, "dispute lost", dispute={"id": "dp_1", "payment_intent": "pi_card"}
		)
		self._run_all(inv)
		self.gateway.refund.assert_not_called()
		lost = self._refund(inv, "Dispute")
		self.assertEqual(lost.status, "Completed")
		out = next(p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == "dp_1")
		self.assertEqual(out["paid_from"], "Stripe Clearing INR - TC")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)  # the wallet part comes back too


class TestRefused(CorrectionsTestCase):
	def test_an_unpaid_invoice(self):
		inv = self._paid_invoice()
		frappe.db.set_value("Invoice", inv, "status", "Open")
		with self.assertRaises(frappe.ValidationError):
			corrections.cancel_and_refund(inv, "x")

	def test_past_the_gst_credit_note_deadline(self):
		inv = self._paid_invoice(paid_at="2024-05-01 10:00:00")  # year to 31 Mar 2025, due by 30 Nov 2025
		with self.assertRaises(frappe.ValidationError):
			corrections.cancel_and_refund(inv, "x")


class TestDisputeWebhook(CorrectionsTestCase):
	def _event(self, event_type, status="needs_response", amount=3540):
		payload = {
			"id": f"evt_{frappe.generate_hash(length=8)}",
			"type": event_type,
			"data": {
				"object": {
					"object": "dispute",
					"id": "dp_1",
					"payment_intent": "pi_card",
					"amount": round(amount * 100),
					"currency": "inr",
					"status": status,
					"reason": "fraudulent",
				}
			},
		}
		event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": "Stripe",
				"gateway_event_id": payload["id"],
				"event_type": event_type,
				"raw_payload": frappe.as_json(payload),
				"status": "Received",
			}
		).insert(ignore_permissions=True)
		from central.billing.payments.charges import apply_webhook

		return apply_webhook(event.name)

	def _comments(self, invoice):
		return frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": invoice}, pluck="content"
		)

	def test_an_opened_dispute_is_noted(self):
		inv = self._paid_invoice()
		self.assertEqual(self._event("charge.dispute.created")["result"], "noted")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		self.assertTrue(any("dp_1 opened" in c for c in self._comments(inv)))

	def test_losing_the_whole_charge_cancels_the_invoice(self):
		inv = self._paid_invoice()
		self.assertEqual(self._event("charge.dispute.closed", status="lost")["result"], "cancelled")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Cancelled")
		lost = self._refund(inv, "Dispute")
		self.assertEqual((lost.amount, lost.gateway_refund_id), (3540, "dp_1"))

	def test_losing_part_of_the_charge_credits_that_part(self):
		inv = self._paid_invoice()
		self.assertEqual(
			self._event("charge.dispute.closed", status="lost", amount=1000)["result"], "partly_refunded"
		)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		self._run_all(inv)
		lost = self._refund(inv, "Dispute")
		self.assertEqual((lost.partial, lost.amount, lost.gateway_refund_id), (1, 1000, "dp_1"))
		self.gateway.refund.assert_not_called()
		self.assertTrue(lost.credit_note_id and lost.payment_record_id)

	def test_a_won_dispute_changes_nothing(self):
		inv = self._paid_invoice()
		self.assertEqual(self._event("charge.dispute.closed", status="won")["result"], "won")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")


class TestRetryFailedRefund(CorrectionsTestCase):
	def test_a_refused_refund_is_retried_with_a_new_key(self):
		self.gateway.refund.return_value = RefundResult(
			success=False, status="failed", gateway_refund_id=None, raw={}
		)
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		card = self._refund(inv, "Source")
		self.assertEqual(card.status, "Failed")

		from central.billing.platform import alerts

		self.assertIn(inv, [a["subject"] for a in alerts.failed_refunds()])

		self.gateway.refund.return_value = RefundResult(
			success=True, status="Completed", gateway_refund_id="re_2", raw={}
		)
		self.assertEqual(corrections.retry_failed_refunds(inv), 1)
		self._run_all(inv)
		card.reload()
		self.assertEqual((card.status, card.attempts, card.gateway_refund_id), ("Completed", 1, "re_2"))
		self.assertEqual(self.gateway.refund.call_args.args[3], f"{card.name}-1")
		self.assertTrue(card.payment_record_id)  # now recorded in the accounting system

	def test_nothing_to_retry(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		self.assertEqual(corrections.retry_failed_refunds(inv), 0)


class TestPromotionalReturn(CorrectionsTestCase):
	def test_cancelling_reverses_the_promotional_settlement(self):
		inv = self._paid_invoice()
		frappe.db.set_value(
			"Invoice", inv, {"credit_applied": 2500, "promotional_record_id": "JE-PROMO"}
		)  # 500 of the wallet part was promotional
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		journal = self.remote.posts("Journal Entry")[-1]
		expense, party = journal["accounts"]
		self.assertEqual(journal["cheque_no"], f"{inv}-promotional-return")
		self.assertEqual(
			(expense["credit_in_account_currency"], party["debit_in_account_currency"]), (500, 500)
		)
		self.assertEqual(party["reference_name"], frappe.db.get_value("Invoice", inv, "credit_note_id"))
		self.assertTrue(self._refund(inv, "Wallet").promotional_record_id)


class TestRefundPart(CorrectionsTestCase):
	def _wallet_paid(self):
		"""8,000 + 1,440 GST, all from the wallet: 8,000 credit and 1,440 advance GST."""
		inv = self._paid_invoice()
		frappe.db.delete("Payment Attempt", {"invoice": inv})
		frappe.db.set_value(
			"Invoice",
			inv,
			{
				"subtotal": 8000,
				"output_tax_amount": 1440,
				"total": 9440,
				"credit_applied": 8000,
				"advance_applied": 8000,
				"advance_tax_applied": 1440,
				"amount_paid": 0,
			},
		)
		return inv

	def test_a_part_goes_back_to_the_wallet_with_its_gst(self):
		inv = self._wallet_paid()
		corrections.refund_part(inv, 1180, "two days of downtime")
		self._run_all(inv)

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		refund = self._refund(inv, "Wallet")
		self.assertEqual((refund.partial, refund.net_amount, refund.tax_amount), (1, 1000, 180))
		back = frappe.get_doc(
			"Credit Ledger Entry", {"reference_type": "Refund", "reference_name": refund.name}
		)
		self.assertEqual((back.amount, back.tax_amount, back.paid_in), (1000, 180, 1))

		note = next(p for p in self.remote.posts("Sales Invoice") if p.get("is_return"))
		self.assertEqual((note["return_against"], note["naming_series"]), (SALES_INVOICE, "CN/.TFY./.#####"))
		self.assertEqual([(i["qty"], i["rate"]) for i in note["items"]], [(-1, 1000)])
		self.assertTrue(note["taxes"])
		self.assertEqual(refund.credit_note_id, self.remote.posted[0][1])

		out = next(p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == refund.name)
		self.assertEqual((out["paid_from"], out["paid_amount"]), ("Wallet Clearing INR - TC", 1180))
		advance = next(
			p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == f"{refund.name}-advance"
		)
		self.assertEqual(
			frappe.db.get_value("Credit Ledger Entry", back.name, "advance_id"), refund.advance_id
		)
		self.assertEqual(sum(t["tax_amount"] for t in advance["taxes"]), 180)

	def test_a_wallet_paid_invoice_cannot_refund_to_a_card(self):
		inv = self._wallet_paid()
		with self.assertRaises(frappe.ValidationError):
			corrections.refund_part(inv, 1180, "x", destination="Source")

	def test_a_part_back_to_the_card_that_paid(self):
		inv = self._paid_invoice()  # 3,540 by card
		corrections.refund_part(inv, 1000, "goodwill", destination="Source")
		self._run_all(inv)
		refund = self._refund(inv, "Source")
		self.assertEqual((refund.status, refund.gateway_refund_id), ("Completed", "re_1"))
		self.assertEqual(self.gateway.refund.call_args.args[1], 1000)
		self.assertEqual(frappe.db.get_value("Payment Attempt", refund.payment_attempt, "status"), "Captured")
		out = next(p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == "re_1")
		self.assertEqual(out["paid_from"], "Stripe Clearing INR - TC")

	def test_more_than_the_card_paid_is_refused(self):
		inv = self._paid_invoice()
		with self.assertRaises(frappe.ValidationError):
			corrections.refund_part(inv, 4000, "x", destination="Source")

	def test_no_more_than_is_left(self):
		inv = self._wallet_paid()
		corrections.refund_part(inv, 9000, "x")
		with self.assertRaises(frappe.ValidationError):
			corrections.refund_part(inv, 500, "x")  # only 440 left

	def test_a_partly_refunded_invoice_is_not_cancelled_whole(self):
		inv = self._wallet_paid()
		corrections.refund_part(inv, 1180, "x")
		with self.assertRaises(frappe.ValidationError):
			corrections.cancel_and_refund(inv, "x")
