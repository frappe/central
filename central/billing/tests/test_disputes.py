# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Gateway refunds that settle later, and card disputes against a paid invoice."""

from unittest.mock import patch

import frappe

from central.billing.gateways.base import RefundResult
from central.billing.payments import corrections
from central.billing.revenue import credits
from central.billing.tests.test_corrections import TEAM, CorrectionsTestCase


class TestDispute(CorrectionsTestCase):
	def test_a_pending_refund_is_not_counted_as_given_back(self):
		self.gateway.refund.return_value = RefundResult(
			status="Pending", gateway_refund_id="re_pending", raw={}
		)
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)

		card = self._refund(inv, "Source")
		self.assertEqual(card.status, "Pending")
		self.assertEqual(frappe.db.get_value("Payment Attempt", card.payment_attempt, "status"), "Captured")
		self.assertFalse(card.payment_record_id)  # the accounting payment-out waits for the money

	def test_a_pending_refund_completes_on_its_webhook(self):
		self.gateway.refund.return_value = RefundResult(
			status="Pending", gateway_refund_id="re_pending", raw={}
		)
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		event = self._refund_event("re_pending", "succeeded")

		out = corrections.apply_refund_event(event)

		card = self._refund(inv, "Source")
		self.assertEqual((out["status"], card.status), ("Completed", "Completed"))
		self.assertEqual(frappe.db.get_value("Payment Attempt", card.payment_attempt, "status"), "Refunded")

	def test_a_pending_refund_that_fails_is_kept_for_a_person(self):
		from central.billing.payments import reconciliation

		self.gateway.refund.return_value = RefundResult(
			status="Pending", gateway_refund_id="re_pending", raw={}
		)
		self.gateway.get_refund_status.return_value = "Failed"
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)

		with patch("central.billing.payments.reconciliation._adapter", return_value=self.gateway):
			reconciliation.reconcile_pending_refunds()

		self.assertEqual(self._refund(inv, "Source").status, "Failed")

	def test_a_completed_refund_the_gateway_fails_later_is_flagged(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		event = self._refund_event("re_1", "failed")

		out = corrections.apply_refund_event(event)

		card = self._refund(inv, "Source")
		self.assertEqual((out["result"], card.status), ("flagged", "Completed"))
		self.assertEqual(frappe.db.get_value("Payment Attempt", card.payment_attempt, "status"), "Refunded")
		self.assertEqual(frappe.db.get_value("Webhook Event", event, "status"), "Processed")
		self.assertTrue(
			frappe.get_all(
				"Error Log", filters={"method": f"Refund failed after completion on {inv}"}, limit=1
			)
		)
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv}, pluck="content"
		)
		self.assertTrue(any("re_1" in c and "did not get" in c for c in comments))

	def test_a_refund_failed_after_completion_is_flagged_once_for_both_stripe_events(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "customer asked")
		self._run_all(inv)
		first = self._refund_event("re_1", "failed", event_type="refund.failed")
		second = self._refund_event("re_1", "failed")

		results = [corrections.apply_refund_event(e)["result"] for e in (first, second)]

		self.assertEqual(results, ["flagged", "unchanged"])
		logs = frappe.get_all("Error Log", filters={"method": f"Refund failed after completion on {inv}"})
		self.assertEqual(len(logs), 1)
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv}, pluck="content"
		)
		self.assertEqual(sum("did not get" in c for c in comments), 1)

	def _refund_event(self, refund_id, status, event_type="charge.refund.updated"):
		import json

		payload = {
			"type": event_type,
			"data": {"object": {"id": refund_id, "object": "refund", "status": status}},
		}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": "Stripe",
					"gateway_event_id": f"evt_{refund_id}_{status}_{event_type}",
					"event_type": event_type,
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_lost_dispute_is_not_refunded_again(self):
		inv = self._paid_invoice()
		corrections.cancel_and_refund(inv, "dispute lost", dispute={"id": "dp_1", "payment_id": "pi_card"})
		self._run_all(inv)
		self.gateway.refund.assert_not_called()
		lost = self._refund(inv, "Dispute")
		self.assertEqual(lost.status, "Completed")
		out = next(p for p in self.remote.posts("Payment Entry") if p.get("reference_no") == "dp_1")
		self.assertEqual(out["paid_from"], "Stripe Clearing INR - TC")
		self.assertEqual(credits.get_balance(TEAM, "INR")["balance"], 2000)  # the wallet part comes back too


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

	def test_a_lost_razorpay_dispute_cancels_the_invoice(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		inv = self._paid_invoice()
		gateway = make_razorpay_gateway().name
		frappe.db.set_value("Payment Attempt", {"invoice": inv}, "gateway", gateway)

		self.assertEqual(self._razorpay_dispute_lost(gateway)["result"], "cancelled")
		self.assertEqual(self._refund(inv, "Dispute").gateway_refund_id, "disp_r1")

	def test_a_dispute_does_not_match_an_attempt_on_another_gateway(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		inv = self._paid_invoice()  # its attempt is on Stripe, with the same transaction id

		out = self._razorpay_dispute_lost(make_razorpay_gateway().name)

		self.assertEqual(out, {"handled": False, "reason": "no_matching_attempt"})
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")

	def _razorpay_dispute_lost(self, gateway):
		from central.billing.payments.charges import apply_webhook

		payload = {
			"event": "payment.dispute.lost",
			"payload": {"dispute": {"entity": {"id": "disp_r1", "payment_id": "pi_card", "amount": 354000}}},
		}
		event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": gateway,
				"gateway_event_id": "evt_disp_r1",
				"event_type": "payment.dispute.lost",
				"raw_payload": frappe.as_json(payload),
				"status": "Received",
			}
		).insert(ignore_permissions=True)
		return apply_webhook(event.name)

	def test_a_dispute_lost_on_a_late_capture_is_flagged(self):
		inv = self._paid_invoice()
		frappe.get_doc(
			{
				"doctype": "Refund",
				"invoice": inv,
				"team": TEAM,
				"payment_attempt": frappe.db.get_value("Payment Attempt", {"invoice": inv}),
				"amount": 3540,
				"currency": "INR",
				"destination": "Source",
				"late_capture": 1,
				"status": "Failed",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(self._event("charge.dispute.closed", status="lost")["result"], "flagged")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")
		self.assertFalse(frappe.db.exists("Refund", {"invoice": inv, "destination": "Dispute"}))

	def test_a_dispute_lost_on_a_cancelled_invoice_is_flagged(self):
		inv = self._paid_invoice()
		frappe.db.set_value("Invoice", inv, "status", "Cancelled")
		self.assertEqual(self._event("charge.dispute.closed", status="lost")["result"], "flagged")
		self.assertTrue(any("dp_1 lost" in c for c in self._comments(inv)))
