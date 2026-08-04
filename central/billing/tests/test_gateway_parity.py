# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Issue #24 parity: every webhook event type the legacy press integrations
covered is normalised by the new adapters. charge/refund/signature parity is
covered by the shared contract suite (test_stripe_adapter / test_razorpay_adapter)."""

from central.billing.gateways.razorpay_adapter import RazorpayAdapter
from central.billing.gateways.stripe_adapter import StripeAdapter
from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

# Event types the working press integrations handled.
STRIPE_EVENTS = ["payment_intent.succeeded", "payment_intent.payment_failed", "charge.refunded"]
RAZORPAY_EVENTS = ["order.paid", "payment.captured", "payment.failed", "refund.processed"]


class TestGatewayEventParity(IntegrationTestCase):
	def test_stripe_event_types_normalise(self):
		adapter = StripeAdapter(make_stripe_gateway())
		for etype in STRIPE_EVENTS:
			event = adapter.parse_webhook_event({"id": "evt_1", "type": etype}, {})
			self.assertEqual(event.event_type, etype)
			self.assertEqual(event.gateway_event_id, "evt_1")

	def test_razorpay_event_types_normalise(self):
		adapter = RazorpayAdapter(make_razorpay_gateway())
		for etype in RAZORPAY_EVENTS:
			event = adapter.parse_webhook_event(
				{"event": etype, "payload": {}}, {"X-Razorpay-Event-Id": "evt_r"}
			)
			self.assertEqual(event.event_type, etype)
			self.assertEqual(event.gateway_event_id, "evt_r")
