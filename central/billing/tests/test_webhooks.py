# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import razorpay
import stripe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

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
			process_webhook("Stripe", PAYLOAD, HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)
		self.assertEqual(enqueue.call_count, 1)

	def test_invalid_signature_returns_400_with_zero_db_writes(self):
		with signature(valid=False), patch("frappe.enqueue") as enqueue:
			process_webhook("Stripe", PAYLOAD, HEADERS)

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
				process_webhook("Stripe", PAYLOAD, HEADERS)
		parse.assert_not_called()

	def test_replayed_event_is_deduped(self):
		with signature(valid=True), patch("frappe.enqueue") as enqueue:
			process_webhook("Stripe", PAYLOAD, HEADERS)
			process_webhook("Stripe", PAYLOAD, HEADERS)

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
			process_webhook("Razorpay", R_PAYLOAD, R_HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)
		self.assertEqual(enqueue.call_count, 1)

	def test_invalid_signature_returns_400_with_zero_db_writes(self):
		with razorpay_signature(valid=False), patch("frappe.enqueue") as enqueue:
			process_webhook("Razorpay", R_PAYLOAD, R_HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 400)
		self.assertEqual(self._events(), 0)
		self.assertEqual(enqueue.call_count, 0)


import json

from central.billing.payments import charges
from central.billing.revenue import credits
from central.billing.tests.utils import ensure_team

TOPUP_TEAM = "team-topup-wh"


def _topup_payload(payment_id, team, amount_paisa=100000, currency="INR"):
	return json.dumps({
		"event": "payment.captured",
		"payload": {"payment": {"entity": {
			"id": payment_id,
			"amount": amount_paisa,
			"currency": currency,
			"notes": {"team": team, "purpose": "wallet_topup"},
		}}},
	})


class TestWalletTopupWebhookBackstop(IntegrationTestCase):
	"""The `payment.captured` webhook is the server-authoritative backstop for a
	wallet top-up when the browser confirm callback never lands — and it must not
	double-credit beside a confirm that did land (idempotent on the payment id)."""

	def setUp(self):
		ensure_team(TOPUP_TEAM)
		self.gateway = make_razorpay_gateway().name
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Credit Ledger Entry", {"team": TOPUP_TEAM})
		frappe.db.delete("Credit Wallet", {"team": TOPUP_TEAM})
		frappe.db.delete("Webhook Event", {"gateway": self.gateway})

	def _store_event(self, payment_id, event_type="payment.captured", **kw):
		return frappe.get_doc({
			"doctype": "Webhook Event",
			"gateway": self.gateway,
			"gateway_event_id": f"evt_{payment_id}_{frappe.generate_hash(length=6)}",
			"event_type": event_type,
			"raw_payload": _topup_payload(payment_id, TOPUP_TEAM, **kw),
			"status": "Received",
		}).insert(ignore_permissions=True)

	def _credits_for(self, payment_id):
		return frappe.get_all(
			"Credit Ledger Entry",
			filters={"gateway_payment_id": payment_id}, fields=["name", "amount", "entry_type"],
		)

	def test_captured_topup_webhook_books_one_credit(self):
		pid = "pay_backstop_1"
		ev = self._store_event(pid)

		out = charges.apply_webhook(ev.name)

		self.assertEqual(out["result"], "topup_credited")
		entries = self._credits_for(pid)
		self.assertEqual(len(entries), 1)
		self.assertEqual(entries[0]["entry_type"], "Credit")
		self.assertEqual(entries[0]["amount"], 1000.0)  # 100000 paisa -> ₹1000
		self.assertEqual(frappe.db.get_value("Webhook Event", ev.name, "status"), "Processed")
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_confirm_then_webhook_does_not_double_credit(self):
		pid = "pay_backstop_2"
		# Browser confirm landed first (what confirm_topup does).
		credits.purchase(TOPUP_TEAM, 1000, "INR", reference_name=pid, gateway_payment_id=pid)
		# Backstop webhook arrives for the same payment.
		out = charges.apply_webhook(self._store_event(pid).name)

		self.assertEqual(out["result"], "topup_credited")  # handled, but…
		self.assertEqual(len(self._credits_for(pid)), 1)    # …no second entry
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_replayed_webhook_credits_once(self):
		pid = "pay_backstop_3"
		charges.apply_webhook(self._store_event(pid).name)
		charges.apply_webhook(self._store_event(pid).name)  # duplicate delivery

		self.assertEqual(len(self._credits_for(pid)), 1)
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_non_captured_topup_event_credits_nothing(self):
		pid = "pay_backstop_4"
		ev = self._store_event(pid, event_type="payment.authorized")

		out = charges.apply_webhook(ev.name)

		self.assertFalse(out["handled"])
		self.assertEqual(out["reason"], "topup_not_captured")
		self.assertEqual(len(self._credits_for(pid)), 0)
		self.assertEqual(frappe.db.get_value("Webhook Event", ev.name, "status"), "Ignored")

	def test_incomplete_topup_is_ignored_not_credited(self):
		# purpose=wallet_topup but no team in notes -> never credit a guess.
		payload = json.loads(_topup_payload("pay_backstop_5", TOPUP_TEAM))
		payload["payload"]["payment"]["entity"]["notes"].pop("team")
		ev = frappe.get_doc({
			"doctype": "Webhook Event", "gateway": self.gateway,
			"gateway_event_id": "evt_incomplete_topup", "event_type": "payment.captured",
			"raw_payload": json.dumps(payload), "status": "Received",
		}).insert(ignore_permissions=True)

		out = charges.apply_webhook(ev.name)

		self.assertFalse(out["handled"])
		self.assertEqual(out["reason"], "topup_incomplete")
		self.assertEqual(frappe.db.get_value("Webhook Event", ev.name, "status"), "Ignored")
