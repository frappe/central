# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import razorpay
import stripe
from frappe.tests import IntegrationTestCase

from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.payments.webhooks import process_webhook

EVENT_ID = "evt_webhook_500"
PAYLOAD = (
	b'{"id":"' + EVENT_ID.encode() + b'","type":"payment_intent.succeeded",'
	b'"data":{"object":{"id":"pi_x"}}}'
)
HEADERS = {"Stripe-Signature": "t=1,v1=deadbeef"}


@contextmanager
def signature(valid: bool):
	if valid:
		cm = patch.object(stripe.Webhook, "construct_event", return_value={"id": EVENT_ID})
	else:
		err = stripe.error.SignatureVerificationError("bad sig", "sig-header")
		cm = patch.object(stripe.Webhook, "construct_event", side_effect=err)
	with cm:
		yield


class TestStripeWebhookReceiver(IntegrationTestCase):
	def setUp(self):
		make_stripe_gateway()
		frappe.db.delete("Webhook Event", {"gateway_event_id": EVENT_ID})

	def _events(self):
		return frappe.db.count("Webhook Event", {"gateway_event_id": EVENT_ID})

	def test_valid_signed_event_is_stored_and_enqueued(self):
		with signature(valid=True), patch("frappe.enqueue") as enqueue:
			process_webhook("stripe", PAYLOAD, HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)
		self.assertEqual(enqueue.call_count, 1)

	def test_invalid_signature_returns_400_with_zero_db_writes(self):
		with signature(valid=False), patch("frappe.enqueue") as enqueue:
			process_webhook("stripe", PAYLOAD, HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 400)
		self.assertEqual(self._events(), 0)
		self.assertEqual(enqueue.call_count, 0)

	def test_invalid_signature_never_reaches_parsing(self):
		# Regression for the v1 enumeration bug: nothing keyed on payload content
		# runs until the signature is verified.
		with signature(valid=False):
			with patch(
				"central.billing.gateways.stripe_adapter.StripeAdapter.parse_webhook_event"
			) as parse:
				process_webhook("stripe", PAYLOAD, HEADERS)
		parse.assert_not_called()

	def test_replayed_event_is_deduped(self):
		with signature(valid=True), patch("frappe.enqueue") as enqueue:
			process_webhook("stripe", PAYLOAD, HEADERS)
			process_webhook("stripe", PAYLOAD, HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)  # no duplicate
		self.assertEqual(enqueue.call_count, 1)  # no second job


R_EVENT_ID = "evt_razorpay_webhook_1"
R_PAYLOAD = (
	b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_x"}}}}'
)
R_HEADERS = {"X-Razorpay-Signature": "sig", "X-Razorpay-Event-Id": R_EVENT_ID}


@contextmanager
def razorpay_signature(valid: bool):
	client = MagicMock()
	if valid:
		client.utility.verify_webhook_signature.return_value = True
	else:
		client.utility.verify_webhook_signature.side_effect = razorpay.errors.SignatureVerificationError(
			"bad sig"
		)
	with patch("central.billing.gateways.razorpay_adapter.razorpay.Client", return_value=client):
		yield


class TestRazorpayWebhookReceiver(IntegrationTestCase):
	"""Razorpay routes through the same signature-first receiver (issue #24 parity)."""

	def setUp(self):
		make_razorpay_gateway()
		frappe.db.delete("Webhook Event", {"gateway_event_id": R_EVENT_ID})

	def _events(self):
		return frappe.db.count("Webhook Event", {"gateway_event_id": R_EVENT_ID})

	def test_valid_signed_event_is_stored_and_enqueued(self):
		with razorpay_signature(valid=True), patch("frappe.enqueue") as enqueue:
			process_webhook("razorpay", R_PAYLOAD, R_HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)
		self.assertEqual(enqueue.call_count, 1)

	def test_invalid_signature_returns_400_with_zero_db_writes(self):
		with razorpay_signature(valid=False), patch("frappe.enqueue") as enqueue:
			process_webhook("razorpay", R_PAYLOAD, R_HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 400)
		self.assertEqual(self._events(), 0)
		self.assertEqual(enqueue.call_count, 0)
