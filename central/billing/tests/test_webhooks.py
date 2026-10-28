# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
import razorpay
import stripe

from central.billing.payments.webhooks import process_webhook
from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import run_enqueued_inline

EVENT_ID = "evt_webhook_500"
PAYLOAD = (
	b'{"id":"' + EVENT_ID.encode() + b'","type":"payment_intent.succeeded","data":{"object":{"id":"pi_x"}}}'
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
			with patch("central.billing.gateways.stripe_adapter.StripeAdapter.parse_webhook_event") as parse:
				process_webhook("Stripe", PAYLOAD, HEADERS)
		parse.assert_not_called()

	def test_replayed_event_is_deduped(self):
		with signature(valid=True), patch("frappe.enqueue") as enqueue:
			process_webhook("Stripe", PAYLOAD, HEADERS)
			process_webhook("Stripe", PAYLOAD, HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 200)
		self.assertEqual(self._events(), 1)  # no duplicate
		self.assertEqual(enqueue.call_count, 1)  # no second job


R_PAYLOAD = (
	b'{"event":"payment.captured","created_at":1700000000,"payload":{"payment":{"entity":{"id":"pay_x"}}}}'
)
# Built from the signed body; the X-Razorpay-Event-Id header is outside the signature.
R_EVENT_ID = "payment.captured:1700000000:payment=pay_x"
R_HEADERS = {"X-Razorpay-Signature": "sig", "X-Razorpay-Event-Id": "evt_razorpay_webhook_1"}


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

	def test_a_replay_with_a_new_header_id_is_deduped(self):
		with razorpay_signature(valid=True), patch("frappe.enqueue"):
			process_webhook("Razorpay", R_PAYLOAD, R_HEADERS)
			process_webhook("Razorpay", R_PAYLOAD, {**R_HEADERS, "X-Razorpay-Event-Id": "evt_forged_new"})
		self.assertEqual(self._events(), 1)

	def test_invalid_signature_returns_400_with_zero_db_writes(self):
		with razorpay_signature(valid=False), patch("frappe.enqueue") as enqueue:
			process_webhook("Razorpay", R_PAYLOAD, R_HEADERS)

		self.assertEqual(frappe.local.response.http_status_code, 400)
		self.assertEqual(self._events(), 0)
		self.assertEqual(enqueue.call_count, 0)


import json

from central.billing.gateways.razorpay_adapter import RazorpayAdapter
from central.billing.payments import charges
from central.billing.revenue import credits
from central.billing.tests.utils import ensure_team

TOPUP_TEAM = "team-topup-wh"


def _topup_payload(payment_id, order_id, amount_paisa=100000, currency="INR", status="captured", notes=None):
	return json.dumps(
		{
			"event": "payment.captured",
			"payload": {
				"payment": {
					"entity": {
						"id": payment_id,
						"order_id": order_id,
						"status": status,
						"amount": amount_paisa,
						"currency": currency,
						"notes": notes or {},
					}
				}
			},
		}
	)


class TestWalletTopupWebhookBackstop(IntegrationTestCase):
	"""The `payment.captured` webhook is the server-authoritative backstop for a
	wallet top-up when the browser confirm callback never lands. It credits only the
	Top-up Order the payment's Razorpay order belongs to, and only once."""

	def setUp(self):
		from central.billing.doctype.top_up_order.top_up_order import TopupOrder

		ensure_team(TOPUP_TEAM)
		self.gateway = make_razorpay_gateway().name
		self._purge()
		self.order = TopupOrder.start(TOPUP_TEAM, self.gateway, "INR", 1000, credit=1000)
		self.order.record_gateway_order("order_topup_wh")

	def tearDown(self):
		self._purge()

	def _purge(self):
		for doctype in ("Credit Ledger Entry", "Credit Wallet", "Top-up Order", "Payment Method"):
			frappe.db.delete(doctype, {"team": TOPUP_TEAM})
		frappe.db.delete("Webhook Event", {"gateway": self.gateway})

	def _store_event(self, payment_id, event_type="payment.captured", order_id="order_topup_wh", **kw):
		return frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": f"evt_{payment_id}_{frappe.generate_hash(length=6)}",
				"event_type": event_type,
				"raw_payload": _topup_payload(payment_id, order_id, **kw),
				"status": "Received",
			}
		).insert(ignore_permissions=True)

	def _credits_for(self, payment_id):
		# Stored keys are namespaced by provider; these fixtures are all Razorpay.
		return frappe.get_all(
			"Credit Ledger Entry",
			filters={"gateway_payment_id": f"Razorpay:{payment_id}"},
			fields=["name", "amount", "entry_type"],
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
		self.assertEqual(frappe.db.get_value("Top-up Order", self.order.name, "status"), "Credited")
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_confirm_then_webhook_does_not_double_credit(self):
		pid = "pay_backstop_2"
		payload = json.loads(_topup_payload(pid, "order_topup_wh"))
		self.order.credit_wallet(RazorpayAdapter.payment_from_event(payload))  # the confirm callback

		out = charges.apply_webhook(self._store_event(pid).name)

		self.assertEqual(out["result"], "topup_credited")  # handled, but…
		self.assertEqual(len(self._credits_for(pid)), 1)  # …no second entry
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_replayed_webhook_credits_once(self):
		pid = "pay_backstop_3"
		charges.apply_webhook(self._store_event(pid).name)
		charges.apply_webhook(self._store_event(pid).name)  # duplicate delivery

		self.assertEqual(len(self._credits_for(pid)), 1)
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 1000.0)

	def test_non_captured_topup_event_credits_nothing(self):
		pid = "pay_backstop_4"
		ev = self._store_event(pid, event_type="payment.authorized", status="authorized")

		out = charges.apply_webhook(ev.name)

		self.assertFalse(out["handled"])
		self.assertEqual(out["reason"], "topup_not_captured")
		self.assertEqual(len(self._credits_for(pid)), 0)
		self.assertEqual(frappe.db.get_value("Webhook Event", ev.name, "status"), "Ignored")

	def _store_decline(self, payment_id, order_id):
		event = self._store_event(payment_id, event_type="payment.failed", order_id=order_id, status="failed")
		payload = json.loads(event.raw_payload)
		payload["payload"]["payment"]["entity"].update(
			error_code="BAD_REQUEST_ERROR",
			error_reason="insufficient_balance",
			error_description="The account has insufficient balance.",
		)
		event.db_set("raw_payload", json.dumps(payload))
		return event.name

	def test_a_declined_topup_payment_is_kept_on_the_order(self):
		out = charges.apply_webhook(self._store_decline("pay_declined", "order_topup_wh"))

		self.assertEqual(out["result"], "topup_declined")
		order = frappe.get_doc("Top-up Order", self.order.name)
		self.assertEqual(order.status, "Created")  # the payer can try again on it
		self.assertEqual(
			(order.failure_code, order.decline_code), ("BAD_REQUEST_ERROR", "insufficient_balance")
		)
		self.assertEqual(order.failed_attempts, 1)
		self.assertEqual(credits.get_balance(TOPUP_TEAM)["balance"], 0)

	def test_a_decline_counts_on_top_of_what_is_stored(self):
		stale = frappe.get_doc("Top-up Order", self.order.name)
		charges.apply_webhook(self._store_decline("pay_first", "order_topup_wh"))

		stale.record_decline({"failure_code": "card_declined"})  # a copy read before the first

		self.assertEqual(frappe.db.get_value("Top-up Order", self.order.name, "failed_attempts"), 2)

	def test_a_declined_mandate_authorisation_is_kept_on_the_method(self):
		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TOPUP_TEAM,
				"gateway": self.gateway,
				"method_type": "UPI Autopay",
				"status": "Pending Validation",
				"setup_reference": "order_mandate_wh",
			}
		).insert(ignore_permissions=True)

		out = charges.apply_webhook(self._store_decline("pay_mandate", "order_mandate_wh"))

		self.assertEqual(out["result"], "setup_payment_declined")
		method.reload()
		self.assertEqual(method.status, "Pending Validation")
		self.assertEqual(method.decline_code, "insufficient_balance")
		self.assertTrue(
			frappe.db.exists(
				"Billing Event", {"subject": method.name, "event_type": "Payment Method Setup Failed"}
			)
		)

	def test_notes_naming_a_team_credit_nothing(self):
		"""Razorpay Checkout lets the payer set payment notes, so they decide nothing."""
		pid = "pay_backstop_5"
		ev = self._store_event(
			pid,
			order_id="order_not_ours",
			notes={"team": TOPUP_TEAM, "purpose": "wallet_topup", "credit": "999"},
		)

		out = charges.apply_webhook(ev.name)

		self.assertFalse(out["handled"])
		self.assertEqual(len(self._credits_for(pid)), 0)

	def test_a_payment_on_another_gateway_credits_nothing(self):
		"""An order id stored for one gateway does not match a payment on another."""
		pid = "pay_backstop_7"
		self.order.db_set("gateway", make_stripe_gateway().name)

		out = charges.apply_webhook(self._store_event(pid).name)

		self.assertFalse(out["handled"])
		self.assertEqual(len(self._credits_for(pid)), 0)
		self.assertEqual(frappe.db.get_value("Top-up Order", self.order.name, "status"), "Created")

	def test_a_payment_above_the_total_credits_the_surplus_once(self):
		pid = "pay_backstop_8"
		charges.apply_webhook(self._store_event(pid, amount_paisa=150000).name)
		charges.apply_webhook(self._store_event(pid, amount_paisa=150000).name)  # duplicate delivery

		self.assertEqual(len(self._credits_for(pid)), 1)
		surplus = frappe.get_all(
			"Credit Ledger Entry",
			filters={"gateway_payment_id": f"Razorpay:{pid}:surplus"},
			fields=["amount", "tax_amount"],
		)
		self.assertEqual(len(surplus), 1)
		self.assertEqual(surplus[0].amount + surplus[0].tax_amount, 500.0)

	def test_a_short_payment_credits_nothing(self):
		pid = "pay_backstop_6"
		with self.assertRaises(frappe.ValidationError):
			charges.apply_webhook(self._store_event(pid, amount_paisa=100).name)
		self.assertEqual(len(self._credits_for(pid)), 0)


class TestFailedWebhookIsKept(IntegrationTestCase):
	"""A handler that raises leaves its work undone, the event Failed with the error, and
	the hourly sweep applies it again."""

	def setUp(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		self.gateway = make_stripe_gateway().name
		frappe.db.delete("Webhook Event", {"gateway": self.gateway})
		self.event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": "evt_crash",
				"event_type": "payment_intent.succeeded",
				"raw_payload": "{}",
				"status": "Received",
			}
		).insert(ignore_permissions=True)

	def test_a_crash_marks_the_event_failed_and_undoes_its_writes(self):
		from central.billing.payments import webhooks

		def crash(event_name):
			frappe.db.set_value("Webhook Event", event_name, "processed_at", frappe.utils.now_datetime())
			raise RuntimeError("handler bug")

		with patch("central.billing.payments.charges.apply_webhook", side_effect=crash):
			webhooks.handle_webhook_event(self.event.name)

		row = frappe.db.get_value(
			"Webhook Event", self.event.name, ["status", "retry_count", "processed_at", "error"], as_dict=True
		)
		self.assertEqual((row.status, row.retry_count, row.processed_at), ("Failed", 1, None))
		self.assertIn("handler bug", row.error)

	def test_the_sweep_retries_a_failed_event(self):
		from central.billing.payments import webhooks

		with patch("central.billing.payments.charges.apply_webhook", side_effect=RuntimeError("down")):
			webhooks.handle_webhook_event(self.event.name)
		with (
			patch("central.billing.payments.charges.apply_webhook") as apply,
			patch("frappe.enqueue", side_effect=run_enqueued_inline),
		):
			retried = webhooks.retry_failed_webhooks()
		self.assertIn(self.event.name, retried)
		apply.assert_called_once_with(self.event.name)

	def test_an_event_that_keeps_failing_waits_for_an_operator(self):
		from central.billing.payments import webhooks

		frappe.db.set_value(
			"Webhook Event", self.event.name, {"status": "Failed", "retry_count": webhooks.MAX_TRIES}
		)
		self.assertNotIn(self.event.name, webhooks.retry_failed_webhooks())
