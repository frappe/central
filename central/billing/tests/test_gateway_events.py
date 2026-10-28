# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stripe events beyond capture: cancelled intents, card events and disputes, each
recorded on the payment or card it is about."""

import json
from unittest.mock import patch

import frappe

from central.billing.payments import webhooks
from central.billing.tests.test_charges import GATEWAY, TEAM, ChargeTestBase, stub_adapter


class TestGatewayEvents(ChargeTestBase):
	def _event(self, event_id: str, event_type: str, gateway_object: dict) -> str:
		payload = {"id": event_id, "type": event_type, "data": {"object": gateway_object}}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": GATEWAY,
					"gateway_event_id": event_id,
					"event_type": event_type,
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _authorised_attempt(self, invoice: str, transaction_id: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": invoice,
					"team": TEAM,
					"gateway": GATEWAY,
					"payment_method": self.method,
					"amount": 1000,
					"currency": "INR",
					"status": "Authorised",
					"gateway_transaction_id": transaction_id,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_cancelled_authorisation_fails_the_attempt_with_its_reason(self):
		attempt = self._authorised_attempt(self._open_invoice(), "pi_cancel")
		event = self._event(
			"evt_cancel",
			"payment_intent.canceled",
			{
				"id": "pi_cancel",
				"object": "payment_intent",
				"status": "canceled",
				"cancellation_reason": "automatic",
			},
		)
		with patch("central.billing.payments.collection.collect_invoice") as collect:
			webhooks.handle_webhook_event(event)

		doc = frappe.get_doc("Payment Attempt", attempt)
		self.assertEqual(doc.status, "Failed")
		self.assertEqual((doc.failure_code, doc.decline_code), ("canceled", "automatic"))
		collect.assert_called_once()
		self.assertEqual(frappe.db.get_value("Webhook Event", event, "payment_attempt"), attempt)

	def test_a_card_detached_at_the_gateway_is_cancelled(self):
		event = self._event("evt_detach", "payment_method.detached", {"id": "pm_card"})
		webhooks.handle_webhook_event(event)

		method = frappe.get_doc("Payment Method", self.method)
		self.assertEqual(method.status, "Cancelled")
		self.assertFalse(method.is_default)
		self.assertEqual(
			frappe.db.get_value("Webhook Event", event, ["status", "payment_method"]),
			("Processed", self.method),
		)

	def test_a_detached_card_we_do_not_know_is_ignored(self):
		event = self._event("evt_detach_other", "payment_method.detached", {"id": "pm_other"})
		webhooks.handle_webhook_event(event)

		self.assertEqual(frappe.db.get_value("Webhook Event", event, "status"), "Ignored")
		self.assertEqual(frappe.db.get_value("Payment Method", self.method, "status"), "Active")

	def test_a_failed_card_setup_is_recorded_and_the_card_can_still_be_confirmed(self):
		pending = (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Pending Validation",
					"setup_reference": "seti_1",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		event = self._event(
			"evt_setup_failed",
			"setup_intent.setup_failed",
			{
				"id": "seti_1",
				"last_setup_error": {
					"code": "card_declined",
					"decline_code": "do_not_honor",
					"message": "Your card was declined.",
				},
			},
		)
		webhooks.handle_webhook_event(event)

		method = frappe.get_doc("Payment Method", pending)
		self.assertEqual(method.status, "Pending Validation")
		self.assertEqual((method.failure_code, method.decline_code), ("card_declined", "do_not_honor"))
		self.assertEqual(method.failure_reason, "Your card was declined.")
		self.assertEqual(method.failed_attempts, 1)
		self.assertTrue(
			frappe.db.exists(
				"Billing Event",
				{"subject": pending, "event_type": "Payment Method Setup Failed", "reason": "card_declined"},
			)
		)
		self.assertEqual(frappe.db.get_value("Webhook Event", event, "payment_method"), pending)

	def test_a_dispute_is_linked_to_the_charge_it_is_about(self):
		invoice = self._open_invoice()
		with stub_adapter(success=True, txn_id="pi_disputed"):
			from central.billing.payments import charges

			attempt = charges.pay_invoice(invoice)["attempt"]
		event = self._event(
			"evt_dispute",
			"charge.dispute.created",
			{"id": "dp_1", "payment_intent": "pi_disputed", "amount": 100000, "reason": "fraudulent"},
		)
		webhooks.handle_webhook_event(event)

		self.assertEqual(frappe.db.get_value("Webhook Event", event, "payment_attempt"), attempt)
