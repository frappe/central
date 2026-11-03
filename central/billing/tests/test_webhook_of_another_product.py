# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Frappe Cloud v1 shares the gateway accounts. Only events about Central's records are kept."""

import json
from unittest.mock import patch

import frappe

from central.billing.gateways.razorpay_adapter import RazorpayAdapter
from central.billing.gateways.stripe_adapter import StripeAdapter
from central.billing.payments import webhooks
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def _stripe_event(event_id: str, gateway_object: dict) -> bytes:
	return json.dumps(
		{"id": event_id, "type": "payment_intent.succeeded", "data": {"object": gateway_object}}
	).encode()


def _deliver(body: bytes) -> dict:
	with (
		patch.object(StripeAdapter, "verify_webhook_signature", return_value=True),
		patch("frappe.enqueue"),
	):
		return webhooks.process_webhook("Stripe", body, {"Stripe-Signature": "x"})


class TestWebhookOfAnotherProduct(IntegrationTestCase):
	def setUp(self):
		make_stripe_gateway()

	def test_an_event_about_nothing_of_ours_is_acknowledged_and_not_stored(self):
		result = _deliver(_stripe_event("evt_press", {"id": "pi_press", "metadata": {"receipt": "press-1"}}))

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertFalse(result["stored"])
		self.assertFalse(frappe.db.exists("Webhook Event", {"gateway_event_id": "evt_press"}))

	def test_an_event_with_our_receipt_is_stored(self):
		order = frappe.get_doc(
			{"doctype": "Top-up Order", "team": "team-webhook-filter", "gateway": "Stripe", "currency": "INR"}
		)
		order.flags.ignore_links = True
		order.flags.ignore_mandatory = True
		order.flags.ignore_validate = True
		order.insert(ignore_permissions=True)

		_deliver(_stripe_event("evt_ours", {"id": "pi_unsaved", "metadata": {"receipt": order.name}}))

		self.assertTrue(frappe.db.exists("Webhook Event", {"gateway_event_id": "evt_ours"}))

	def test_razorpay_notes_cannot_claim_an_event(self):
		payload = {"payload": {"payment": {"entity": {"id": "pay_x", "notes": {"receipt": "anything"}}}}}

		self.assertEqual(RazorpayAdapter.webhook_references(payload), {"pay_x"})

	def test_an_event_with_no_ids_is_not_stored(self):
		self.assertFalse(webhooks.is_central_event(StripeAdapter(frappe._dict()), {"data": {"object": {}}}))
