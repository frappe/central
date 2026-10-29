# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Charge invoice -> Payment Attempt -> webhook -> Paid (issue #10)."""

import json
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.catalog import subscriptions
from central.billing.doctype.payment_attempt.payment_attempt import idempotency_key
from central.billing.gateways.base import GatewayError, PaymentResult
from central.billing.payments import charges, webhooks
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_atlas_instance, ensure_team, make_plan, stripe_intent

TEAM = "team-charge"
CLUSTER = "ap-south-1"
PLAN = "bundle-charge-test"
GATEWAY = "Stripe"


def run_workers(n, fn):
	site = frappe.local.site
	results = {}

	def worker(i):
		frappe.init(site=site)
		frappe.connect()
		frappe.set_user("Administrator")
		try:
			results[i] = fn(i)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			results[i] = type(e).__name__
		finally:
			frappe.destroy()

	threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	return results


@contextmanager
def stub_adapter(success=True, txn_id="pi_x"):
	adapter = MagicMock()
	adapter.prepare_charge.return_value = None  # Stripe-like: no order to store
	adapter.charge.return_value = PaymentResult(
		success=success,
		status="Captured" if success else "Failed",
		gateway_transaction_id=txn_id if success else None,
		failure_code=None if success else "card_declined",
		failure_reason=None if success else "declined",
	)
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class ChargeTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		make_plan(PLAN)
		make_stripe_gateway()
		self._purge()
		self.method = self._active_card()
		self.sub = subscriptions.create_subscription(
			team=TEAM,
			cluster=CLUSTER,
			plan=PLAN,
			billing_cycle="Monthly",
			default_payment_method=self.method,
			gateway=GATEWAY,
		).name

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Payment Attempt", "Invoice"):
			frappe.db.delete(dt, {"team": TEAM})
		for pm in frappe.get_all("Payment Method", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Payment Method", {"name": pm})
		for we in frappe.get_all("Webhook Event", pluck="name"):
			frappe.db.delete("Webhook Event", {"name": we})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _active_card(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": GATEWAY,
					"method_type": "Card",
					"status": "Active",
					"gateway_method_id": "pm_card",
					"gateway_customer_id": "cus_1",
					"is_default": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _open_invoice(self, total=1000, month=6):
		# A team gets one live invoice per period, so a test that wants several bills
		# has to spread them across months.
		last_day = 30 if month in (4, 6, 9, 11) else 31
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"subscription": self.sub,
					"status": "Open",
					"period_start": f"2026-{month:02d}-01",
					"period_end": f"2026-{month:02d}-{last_day}",
					"currency": "INR",
					"subtotal": total,
					"total": total,
					"credit_applied": 0,
					"expected_collection": total,
					"amount_paid": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _stripe_event(self, gateway_event_id, event_type, txn_id):
		payload = {
			"id": gateway_event_id,
			"type": event_type,
			"data": {"object": stripe_intent(txn_id, event_type)},
		}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": GATEWAY,
					"gateway_event_id": gateway_event_id,
					"event_type": event_type,
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)


class TestChargeInvoice(ChargeTestBase):
	def test_charge_creates_attempt_but_does_not_mark_paid(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_1") as adapter:
			result = charges.pay_invoice(inv)

		adapter.charge.assert_called_once()
		# The key handed to the gateway is worked out from the invoice + retry number.
		attempt = frappe.get_doc("Payment Attempt", result["attempt"])
		self.assertEqual(adapter.charge.call_args.args[2], attempt.idempotency_key)
		self.assertEqual(attempt.idempotency_key, idempotency_key(inv, 0))
		self.assertEqual(attempt.status, "Captured")
		self.assertEqual(attempt.gateway_transaction_id, "pi_1")
		# Crucially: invoice is NOT Paid on the charge response.
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_declined_charge_records_failed_attempt(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=False):
			result = charges.pay_invoice(inv)
		self.assertFalse(result["charged"])
		attempt = frappe.get_doc("Payment Attempt", result["attempt"])
		self.assertEqual(attempt.status, "Failed")
		self.assertEqual(attempt.failure_code, "card_declined")
		event_reason = frappe.db.get_value(
			"Billing Event", {"subject": attempt.name, "to_state": "Failed"}, "reason"
		)
		self.assertEqual(event_reason, "card_declined")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_webhook_settles_invoice_to_paid(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_settle"):
			charges.pay_invoice(inv)

		event = self._stripe_event("evt_1", "payment_intent.succeeded", "pi_settle")
		out = charges.apply_webhook(event)

		self.assertEqual(out["result"], "paid")
		invoice = frappe.get_doc("Invoice", inv)
		self.assertEqual(invoice.status, "Paid")
		self.assertEqual(invoice.amount_paid, 1000.0)
		# Notification logged (the #20 suite is the real sender).
		comments = frappe.get_all(
			"Comment", {"reference_doctype": "Invoice", "reference_name": inv, "comment_type": "Info"}
		)
		self.assertTrue(comments)

	def _hosted_checkout_event(self, gateway_event_id, receipt, amount_minor, txn_id="pi_hosted"):
		"""A Stripe capture webhook for a hosted checkout, carrying our receipt in metadata."""
		intent = {
			"id": txn_id,
			"object": "payment_intent",
			"status": "succeeded",
			"amount_received": amount_minor,
			"currency": "inr",
			"metadata": {"receipt": receipt, "purpose": "invoice_payment"},
		}
		payload = {"id": gateway_event_id, "type": "payment_intent.succeeded", "data": {"object": intent}}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": GATEWAY,
					"gateway_event_id": gateway_event_id,
					"event_type": "payment_intent.succeeded",
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _hosted_attempt(self, inv):
		attempt = charges._claim_on_session_attempt(inv, GATEWAY)["attempt"]
		frappe.db.set_value("Payment Attempt", attempt, "gateway_order_id", "cs_hosted")
		return attempt

	def test_hosted_checkout_webhook_settles_the_attempt_it_names(self):
		inv = self._open_invoice(1000)
		attempt = self._hosted_attempt(inv)

		out = charges.apply_webhook(self._hosted_checkout_event("evt_hosted_1", attempt, 100000))

		self.assertEqual(out["result"], "paid")
		invoice = frappe.get_doc("Invoice", inv)
		self.assertEqual(invoice.status, "Paid")
		self.assertEqual(invoice.amount_paid, 1000.0)
		# The capture is on the attempt, so a refund can find it.
		self.assertEqual(
			frappe.db.get_value("Payment Attempt", attempt, "gateway_transaction_id"), "pi_hosted"
		)
		second = charges.apply_webhook(self._hosted_checkout_event("evt_hosted_2", attempt, 100000))
		self.assertEqual(second["result"], "duplicate")

	def test_payment_notes_never_settle_an_invoice(self):
		"""Notes and metadata naming an invoice settle nothing without a stored attempt."""
		inv = self._open_invoice(1000)
		event = self._hosted_checkout_event("evt_notes", "not-our-receipt", 100000)
		payload = json.loads(frappe.db.get_value("Webhook Event", event, "raw_payload"))
		payload["data"]["object"]["metadata"]["invoice"] = inv
		frappe.db.set_value("Webhook Event", event, "raw_payload", json.dumps(payload))

		self.assertEqual(charges.apply_webhook(event)["reason"], "no_matching_attempt")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_a_payment_on_another_gateway_settles_nothing(self):
		"""A transaction id stored for one gateway does not match a payment on another."""
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_other_gateway"):
			attempt = charges.pay_invoice(inv)["attempt"]
		frappe.db.set_value("Payment Attempt", attempt, "gateway", make_razorpay_gateway().name)

		event = self._stripe_event("evt_other_gateway", "payment_intent.succeeded", "pi_other_gateway")

		self.assertEqual(charges.apply_webhook(event)["reason"], "no_matching_attempt")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_a_short_payment_settles_nothing_and_goes_to_the_wallet(self):
		from central.billing.revenue import credits

		inv = self._open_invoice(1000)
		attempt = self._hosted_attempt(inv)

		charges.apply_webhook(self._hosted_checkout_event("evt_short", attempt, 100))

		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")
		# The money was captured, so it must reach a ledger: 1.00 in major units.
		self.assertEqual(frappe.utils.flt(credits.get_balance(TEAM)["balance"]), 1)
		# The short capture no longer holds the invoice, so it can still be paid.
		self.assertIsNone(charges.in_flight_attempt(inv))
		self.assertTrue(charges._claim_on_session_attempt(inv, GATEWAY)["created"])

	def test_a_capture_on_a_paid_invoice_goes_to_the_wallet(self):
		from central.billing.revenue import credits

		inv = self._open_invoice(1000)
		attempt = self._hosted_attempt(inv)
		frappe.db.set_value("Invoice", inv, "status", "Paid")

		charges.apply_webhook(self._hosted_checkout_event("evt_late", attempt, 100000))

		self.assertGreater(frappe.utils.flt(credits.get_balance(TEAM)["balance"]), 0)

	def test_duplicate_success_webhook_is_idempotent(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_dup"):
			charges.pay_invoice(inv)
		e1 = self._stripe_event("evt_1", "payment_intent.succeeded", "pi_dup")
		e2 = self._stripe_event("evt_2", "payment_intent.succeeded", "pi_dup")

		charges.apply_webhook(e1)
		second = charges.apply_webhook(e2)
		self.assertEqual(second["result"], "duplicate")  # already settled, no double-apply
		self.assertEqual(frappe.db.get_value("Invoice", inv, "amount_paid"), 1000.0)

	def test_failure_webhook_leaves_invoice_open(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_fail"):
			charges.pay_invoice(inv)
		event = self._stripe_event("evt_f", "payment_intent.payment_failed", "pi_fail")
		charges.apply_webhook(event)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_authorised_webhook_advances_attempt_without_paying(self):
		inv = self._open_invoice(1000)
		# An authorise-only charge: the sync response holds funds, attempt initiated.
		with stub_adapter(success=False, txn_id="pi_auth") as adapter:
			adapter.charge.return_value = PaymentResult(
				success=False,
				status="Authorised",
				gateway_transaction_id="pi_auth",
				failure_code=None,
				failure_reason=None,
			)
			attempt_name = charges.pay_invoice(inv)["attempt"]
		# Manually leave the attempt at initiated (charge didn't capture).
		frappe.db.set_value(
			"Payment Attempt", attempt_name, {"status": "Initiated", "gateway_transaction_id": "pi_auth"}
		)

		event = self._stripe_event("evt_auth", "payment_intent.amount_capturable_updated", "pi_auth")
		out = charges.apply_webhook(event)

		self.assertEqual(out["result"], "Authorised")
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt_name, "status"), "Authorised")
		# Funds only held — invoice not settled.
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_authorised_webhook_never_walks_back_a_captured_attempt(self):
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_race"):
			attempt_name = charges.pay_invoice(inv)["attempt"]
		# Capture lands first.
		charges.apply_webhook(self._stripe_event("evt_cap", "payment_intent.succeeded", "pi_race"))
		# A late authorise webhook for the same txn must not regress it.
		charges.apply_webhook(
			self._stripe_event("evt_late", "payment_intent.amount_capturable_updated", "pi_race")
		)
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt_name, "status"), "Captured")
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Paid")


class TestDurableIntent(ChargeTestBase):
	"""The attempt is written down before the gateway is called (ADR 0017).

	The failure this prevents: the worker dies after the card is charged but before
	we save anything, so the charge exists at the gateway and nowhere with us. The
	customer gets billed, the invoice stays Open, dunning charges them again, and
	nothing in our data shows any of it happened.
	"""

	def test_attempt_exists_before_the_gateway_is_called(self):
		# Whatever the gateway does, by the time it is asked there is already a saved
		# Initiated attempt naming the amount and the card.
		inv = self._open_invoice(1000)
		seen = {}

		def spy_charge(charge_input, method, key):
			row = frappe.get_all(
				"Payment Attempt", {"invoice": inv}, ["name", "status", "idempotency_key", "amount"]
			)
			seen["attempt"] = row[0] if row else None
			seen["key"] = key
			return PaymentResult(success=True, status="Captured", gateway_transaction_id="pi_spy")

		with stub_adapter(success=True) as adapter:
			adapter.charge.side_effect = spy_charge
			charges.pay_invoice(inv)

		self.assertIsNotNone(seen["attempt"])
		self.assertEqual(seen["attempt"].status, "Initiated")
		self.assertEqual(seen["attempt"].amount, 1000.0)
		self.assertEqual(seen["attempt"].idempotency_key, seen["key"])

	def test_a_gateway_order_is_stored_before_the_charge(self):
		"""A gateway with no charge idempotency key (Razorpay) charges on an order whose id
		is already on the attempt, so a retry finds the payment instead of making another."""
		inv = self._open_invoice(1000)
		seen = {}

		def spy_charge(charge_input, method, key):
			seen["stored"] = frappe.db.get_value("Payment Attempt", {"invoice": inv}, "gateway_order_id")
			seen["sent"] = charge_input.order_id
			return PaymentResult(success=True, status="Captured", gateway_transaction_id="pay_spy")

		with stub_adapter(success=True) as adapter:
			adapter.prepare_charge.return_value = "order_rzp"
			adapter.charge.side_effect = spy_charge
			charges.pay_invoice(inv)

		self.assertEqual(seen, {"stored": "order_rzp", "sent": "order_rzp"})

	def test_gateway_error_leaves_a_resolvable_attempt(self):
		# An error the adapter doesn't map (auth failure, bad response, a crash) used
		# to roll the attempt away. It must now survive, sitting at Initiated, so
		# reconciliation can ask the gateway what actually happened.
		inv = self._open_invoice(1000)
		with stub_adapter(success=True) as adapter:
			adapter.charge.side_effect = GatewayError("boom")
			with self.assertRaises(GatewayError):
				charges.pay_invoice(inv)

		attempts = frappe.get_all("Payment Attempt", {"invoice": inv}, ["name", "status"])
		self.assertEqual(len(attempts), 1)
		self.assertEqual(attempts[0].status, "Initiated")

	def test_lost_attempt_is_retried_with_the_same_key(self):
		# Simulate the crash: the card was charged, then the attempt row was lost.
		# The retry must offer the gateway the SAME key, so it replays the first
		# charge instead of taking the money twice.
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_lost") as first:
			charges.pay_invoice(inv)
		first_key = first.charge.call_args.args[2]

		frappe.db.delete("Payment Attempt", {"invoice": inv})  # the crash

		with stub_adapter(success=True, txn_id="pi_lost") as retry:
			charges.pay_invoice(inv)
		self.assertEqual(retry.charge.call_args.args[2], first_key)

	def test_a_real_retry_gets_a_new_key(self):
		# The other half: once a failed attempt is on record, the next charge is a
		# genuinely new one and must be allowed through the gateway's dedupe.
		inv = self._open_invoice(1000)
		with stub_adapter(success=False) as declined:
			charges.pay_invoice(inv)
		with stub_adapter(success=True, txn_id="pi_retry") as second:
			charges.pay_invoice(inv)

		self.assertNotEqual(second.charge.call_args.args[2], declined.charge.call_args.args[2])
		self.assertEqual(second.charge.call_args.args[2], idempotency_key(inv, 1))

	def test_same_charge_cannot_be_claimed_twice(self):
		# The idempotency key is unique, so a second claim of the same charge is
		# refused by the database even if the in-flight check is bypassed.
		inv = self._open_invoice(1000)
		with stub_adapter(success=True, txn_id="pi_twice"):
			charges.pay_invoice(inv)

		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": inv,
					"team": TEAM,
					"gateway": GATEWAY,
					"payment_method": self.method,
					"amount": 1000,
					"currency": "INR",
					"status": "Initiated",
					"retry_number": 0,
				}
			).insert(ignore_permissions=True)


class TestConcurrentPay(ChargeTestBase):
	def test_concurrent_pay_invoice_makes_one_captured_attempt(self):
		inv = self._open_invoice(1000)
		frappe.db.commit()

		with stub_adapter(success=True, txn_id="pi_once"):
			run_workers(10, lambda i: charges.pay_invoice(inv).get("reason", "charged"))

		frappe.db.rollback()
		attempts = frappe.get_all("Payment Attempt", {"invoice": inv}, ["name", "status"])
		self.assertEqual(len(attempts), 1)  # exactly one attempt created
		self.assertEqual(attempts[0].status, "Captured")  # and only it reaches captured


class TestFullStripeCycle(ChargeTestBase):
	def test_open_charge_webhook_paid(self):
		import stripe

		from central.billing.gateways.stripe_adapter import StripeAdapter

		inv = self._open_invoice(1000)

		# Charge through the REAL StripeAdapter with only the SDK call stubbed.
		with patch.object(
			stripe.PaymentIntent, "create", return_value={"id": "pi_cycle", "status": "succeeded"}
		):
			charges.pay_invoice(inv)
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")  # not paid yet

		# Deliver the webhook through the signature-first receiver, then handle it.
		body = json.dumps(
			{
				"id": "evt_cycle",
				"type": "payment_intent.succeeded",
				"data": {"object": stripe_intent("pi_cycle")},
			}
		).encode()
		with patch.object(StripeAdapter, "verify_webhook_signature", return_value=True):
			webhooks.process_webhook("Stripe", body, {"Stripe-Signature": "x"})

		event_name = frappe.get_all("Webhook Event", {"gateway_event_id": "evt_cycle"}, pluck="name")[0]
		webhooks.handle_webhook_event(event_name)

		invoice = frappe.get_doc("Invoice", inv)
		self.assertEqual(invoice.status, "Paid")
		self.assertEqual(invoice.amount_paid, 1000.0)


class TestLogRetention(ChargeTestBase):
	"""Rolling prune of failed Payment Attempts and handled Webhook Events."""

	def _attempt(self, invoice, status):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": invoice,
					"team": TEAM,
					"gateway": GATEWAY,
					"amount": 1000,
					"currency": "INR",
					"status": status,
					"initiated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _paid_invoice(self):
		inv = self._open_invoice(1000)
		frappe.db.set_value("Invoice", inv, "status", "Paid")
		return inv

	def _far_future(self):
		# Push 'now' past the retention window so every just-created row is old enough.
		return frappe.utils.add_to_date(frappe.utils.now_datetime(), days=400)

	def test_prunes_a_failed_attempt_on_a_settled_invoice(self):
		failed = self._attempt(self._paid_invoice(), "Failed")
		out = charges.cleanup_payment_logs(now=self._far_future())
		self.assertGreaterEqual(out["payment_attempts"], 1)
		self.assertFalse(frappe.db.exists("Payment Attempt", failed))

	def test_keeps_a_captured_attempt_a_refund_or_dispute_needs(self):
		captured = self._attempt(self._paid_invoice(), "Captured")
		charges.cleanup_payment_logs(now=frappe.utils.add_to_date(frappe.utils.now_datetime(), days=2000))
		self.assertTrue(frappe.db.exists("Payment Attempt", captured))

	def test_retention_has_a_floor(self):
		from central.billing import settings

		frappe.db.set_single_value("Billing Settings", "payment_log_retention_days", 0)
		self.addCleanup(frappe.db.set_single_value, "Billing Settings", "payment_log_retention_days", 180)
		self.assertEqual(settings.payment_log_retention_days(), settings.MIN_PAYMENT_LOG_RETENTION_DAYS)

	def test_keeps_attempt_on_unsettled_invoice(self):
		live = self._attempt(self._open_invoice(1000), "Failed")  # invoice still Open
		charges.cleanup_payment_logs(now=self._far_future())
		self.assertTrue(frappe.db.exists("Payment Attempt", live))

	def test_keeps_non_terminal_attempt(self):
		initiated = self._attempt(self._paid_invoice(), "Initiated")
		charges.cleanup_payment_logs(now=self._far_future())
		self.assertTrue(frappe.db.exists("Payment Attempt", initiated))

	def test_keeps_attempt_referenced_by_refund(self):
		refunded = self._attempt(self._paid_invoice(), "Refunded")
		frappe.get_doc({"doctype": "Refund", "payment_attempt": refunded}).insert(ignore_permissions=True)
		charges.cleanup_payment_logs(now=self._far_future())
		self.assertTrue(frappe.db.exists("Payment Attempt", refunded))

	def test_prunes_processed_event_keeps_unhandled(self):
		processed = self._stripe_event("evt_old_done", "payment_intent.succeeded", "pi_x")
		frappe.db.set_value("Webhook Event", processed, "status", "Processed")
		pending = self._stripe_event("evt_old_recv", "payment_intent.succeeded", "pi_y")  # still received
		charges.cleanup_payment_logs(now=self._far_future())
		self.assertFalse(frappe.db.exists("Webhook Event", processed))
		self.assertTrue(frappe.db.exists("Webhook Event", pending))

	def test_respects_config_window(self):
		captured = self._attempt(self._paid_invoice(), "Captured")
		# Wide window (1 year) with 'now' = real now: a fresh row is NOT old enough.
		frappe.db.set_single_value("Billing Settings", "payment_log_retention_days", 365)
		self.addCleanup(frappe.db.set_single_value, "Billing Settings", "payment_log_retention_days", 180)
		charges.cleanup_payment_logs()
		self.assertTrue(frappe.db.exists("Payment Attempt", captured))


class TestDeclineDetail(ChargeTestBase):
	"""An off-session decline surfaces its real reason on the webhook, not the
	sync charge response — apply_webhook must stamp it on the attempt."""

	def _initiated_attempt(self, invoice, txn_id):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": invoice,
					"team": TEAM,
					"gateway": GATEWAY,
					"amount": 1000,
					"currency": "INR",
					"status": "Initiated",
					"gateway_transaction_id": txn_id,
					"initiated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _stripe_failed_event(self, gateway_event_id, txn_id, error):
		payload = {
			"id": gateway_event_id,
			"type": "payment_intent.payment_failed",
			"data": {
				"object": stripe_intent(txn_id, "payment_intent.payment_failed", last_payment_error=error)
			},
		}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": GATEWAY,
					"gateway_event_id": gateway_event_id,
					"event_type": "payment_intent.payment_failed",
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_stripe_failure_webhook_records_decline_code(self):
		inv = self._open_invoice(1000)
		attempt = self._initiated_attempt(inv, "pi_decl")
		event = self._stripe_failed_event(
			"evt_decl",
			"pi_decl",
			{
				"code": "card_declined",
				"decline_code": "insufficient_funds",
				"message": "Your card has insufficient funds.",
			},
		)
		# The failure branch also kicks off method fallback (#28); stub it so this
		# test stays about decline-detail capture, not a live re-charge.
		with patch("central.billing.payments.collection.collect_invoice", return_value=None):
			charges.apply_webhook(event)
		a = frappe.get_doc("Payment Attempt", attempt)
		self.assertEqual(a.status, "Failed")
		self.assertEqual(a.failure_code, "card_declined")
		self.assertEqual(a.decline_code, "insufficient_funds")
		self.assertIn("insufficient funds", a.failure_reason)
		self.assertTrue(a.gateway_response)  # raw error persisted for audit

	def test_a_failure_webhook_without_a_reason_still_gets_a_code(self):
		inv = self._open_invoice(1000)
		attempt = self._initiated_attempt(inv, "pi_bare")
		event = self._stripe_failed_event("evt_bare", "pi_bare", None)
		with patch("central.billing.payments.collection.collect_invoice", return_value=None):
			charges.apply_webhook(event)
		self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "failure_code"), "payment_failed")


class TestFailedPaymentsReport(ChargeTestBase):
	def _failed(self, decline_code, reason, amount=1000, month=6):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Attempt",
					"invoice": self._open_invoice(amount, month),
					"team": TEAM,
					"gateway": GATEWAY,
					"amount": amount,
					"currency": "INR",
					"status": "Failed",
					"failure_code": "card_declined",
					"decline_code": decline_code,
					"failure_reason": reason,
					"initiated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_lists_failures_with_reason_and_summary(self):
		from central.billing.report.failed_payments import failed_payments

		a1 = self._failed("insufficient_funds", "no funds", month=6)
		self._failed("insufficient_funds", "no funds", month=7)
		self._failed("lost_card", "reported lost", month=8)
		# A second failed attempt (a retry) on the SAME invoice as a1 — it must collapse
		# into one row and NOT double-count the amount not collected.
		inv1 = frappe.db.get_value("Payment Attempt", a1, "invoice")
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv1,
				"team": TEAM,
				"gateway": GATEWAY,
				"amount": 1000,
				"currency": "INR",
				"status": "Failed",
				"failure_code": "card_declined",
				"decline_code": "insufficient_funds",
				"failure_reason": "no funds",
				"retry_number": 1,
				"initiated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		# A captured attempt must never appear.
		frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": self._open_invoice(1000, month=9),
				"team": TEAM,
				"gateway": GATEWAY,
				"amount": 1000,
				"currency": "INR",
				"status": "Captured",
				"initiated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

		_columns, rows, _msg, chart, summary = failed_payments.execute({"team": TEAM})
		# 3 distinct invoices (the retry on inv1 collapses into its row, showing 2 attempts).
		self.assertEqual(len(rows), 3)
		self.assertTrue(all(r["decline_code"] for r in rows))
		self.assertEqual(next(r for r in rows if r["invoice"] == inv1)["attempts"], 2)
		by_label = {s["label"]: s["value"] for s in summary}
		self.assertEqual(by_label["Invoices Affected"], 3)
		self.assertEqual(by_label["Failed Attempts"], 4)
		# Amount not collected counts each invoice once (3 × 1000), not per attempt (4000).
		self.assertEqual(by_label["Not Collected (INR)"], 3000)
		self.assertIn("insufficient_funds", by_label["Top Reason"])
		self.assertIn("insufficient_funds", chart["data"]["labels"])
