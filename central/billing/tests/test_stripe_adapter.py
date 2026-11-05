# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import stripe

from central.billing.gateways.base import GatewayTimeout, GatewayUnsupported
from central.billing.gateways.stripe_adapter import StripeAdapter
from central.billing.tests.gateway_contract import GatewayAdapterContract
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def make_stripe_gateway(currencies=(("USD", 1),)):
	"""The Stripe gateway, configured for test. There is only one (named "Stripe")."""
	from central.billing.tests.utils import configure_gateway

	return configure_gateway(
		"Stripe",
		currencies,
		# api_key is Stripe's *publishable* key — the one the browser SDK needs, and
		# what get_payment_method_options hands the client. Set it here so the fixture
		# doesn't silently lean on a stripe_publishable_key in common_site_config.
		api_key="pk_test_123",
		api_secret="sk_test_123",
		webhook_secret="whsec_test_123",
		is_enabled=1,
	)


class TestStripeAdapter(GatewayAdapterContract, IntegrationTestCase):
	def make_adapter(self):
		return StripeAdapter(make_stripe_gateway())

	def webhook_headers(self):
		return {"Stripe-Signature": "t=1,v1=deadbeef"}

	@contextmanager
	def signature_valid(self):
		with patch.object(stripe.Webhook, "construct_event", return_value={"id": "evt_1"}):
			yield

	@contextmanager
	def signature_invalid(self):
		err = stripe.error.SignatureVerificationError("bad sig", "sig-header")
		with patch.object(stripe.Webhook, "construct_event", side_effect=err):
			yield

	def make_charge_inputs(self):
		import frappe

		invoice = frappe._dict(amount=40.0, currency="USD", customer_id="cus_test")
		method = frappe._dict(gateway_method_id="pm_test")
		return invoice, method, "PA-TEST-001"

	@contextmanager
	def charge_succeeds(self, txn_id="txn_ok"):
		import frappe

		intent = frappe._dict(id=txn_id, status="succeeded")
		with patch.object(stripe.PaymentIntent, "create", return_value=intent) as m:
			self._last_create = m
			yield

	@contextmanager
	def charge_declines(self, code="card_declined"):
		err = stripe.error.CardError("Your card was declined.", "Card", code)
		with patch.object(stripe.PaymentIntent, "create", side_effect=err) as m:
			self._last_create = m
			yield

	@contextmanager
	def charge_times_out(self):
		err = stripe.error.APIConnectionError("connection timed out")
		with patch.object(stripe.PaymentIntent, "create", side_effect=err) as m:
			self._last_create = m
			yield

	def captured_idempotency_key(self):
		return self._last_create.call_args.kwargs.get("idempotency_key")

	def make_refund_inputs(self):
		import frappe

		payment_attempt = frappe._dict(gateway_transaction_id="pi_charged")
		return payment_attempt, 40.0, "duplicate charge"

	@contextmanager
	def refund_succeeds(self, refund_id="rfnd_ok"):
		import frappe

		refund = frappe._dict(id=refund_id, status="succeeded")
		with patch.object(stripe.Refund, "create", return_value=refund):
			yield

	def parse_event_inputs(self):
		payload = {
			"id": "evt_123",
			"type": "payment_intent.succeeded",
			"data": {"object": {"id": "pi_charged"}},
		}
		# Stripe carries the event id in the body, so headers are irrelevant.
		return payload, {}, "evt_123", "payment_intent.succeeded"

	def setup_inputs(self):
		import frappe

		return "Team-1", {"customer_id": "cus_test"}

	@contextmanager
	def stub_setup(self):
		import frappe

		intent = frappe._dict(id="seti_1", client_secret="seti_1_secret")
		with patch.object(stripe.SetupIntent, "create", return_value=intent):
			yield

	def validation_inputs(self):
		import frappe

		return frappe._dict(gateway_method_id="pm_test", gateway_customer_id="cus_test")

	@contextmanager
	def stub_validation_success(self):
		import frappe

		intent = frappe._dict(id="pi_micro", status="succeeded")
		with (
			patch.object(stripe.PaymentIntent, "create", return_value=intent),
			patch.object(stripe.Refund, "create", return_value=frappe._dict(status="succeeded")),
		):
			yield

	def expected_account_currency(self):
		return "USD"

	@contextmanager
	def stub_credentials_valid(self):
		account = frappe._dict(id="acct_test", default_currency="usd")
		with patch.object(stripe.Account, "retrieve", return_value=account):
			yield

	@contextmanager
	def stub_credentials_invalid(self):
		err = stripe.error.AuthenticationError("Invalid API Key provided")
		with patch.object(stripe.Account, "retrieve", side_effect=err):
			yield

	# --- optional, gateway-specific capabilities ----------------------------

	def test_register_webhook_returns_endpoint_and_secret(self):
		adapter = self.make_adapter()
		endpoint = frappe._dict(id="we_123", secret="whsec_live_xyz")
		with patch.object(stripe.WebhookEndpoint, "create", return_value=endpoint) as m:
			result = adapter.register_webhook(
				"https://site/api/method/central.billing.payments.webhooks.stripe"
			)
		self.assertEqual(result["endpoint_id"], "we_123")
		self.assertEqual(result["secret"], "whsec_live_xyz")
		self.assertEqual(
			m.call_args.kwargs["url"],
			"https://site/api/method/central.billing.payments.webhooks.stripe",
		)

	def test_get_webhook_reads_url_status_and_events(self):
		adapter = self.make_adapter()
		endpoint = frappe._dict(url="https://site/x", status="enabled", enabled_events=["charge.refunded"])
		with patch.object(stripe.WebhookEndpoint, "retrieve", return_value=endpoint):
			webhook = adapter.get_webhook("we_1")
		self.assertEqual(webhook, {"url": "https://site/x", "is_active": True, "events": ["charge.refunded"]})

	def test_an_endpoint_in_another_account_is_not_found(self):
		from central.billing.gateways.base import WebhookNotFound

		adapter = self.make_adapter()
		missing = stripe.error.InvalidRequestError("No such webhook endpoint", "id", code="resource_missing")
		with patch.object(stripe.WebhookEndpoint, "retrieve", side_effect=missing):
			with self.assertRaises(WebhookNotFound):
				adapter.get_webhook("we_old")

	def test_update_webhook_events_replaces_the_event_list(self):
		adapter = self.make_adapter()
		with patch.object(stripe.WebhookEndpoint, "modify") as modify:
			adapter.update_webhook_events("we_1", "https://site/x", ["payment_intent.canceled"])
		modify.assert_called_once()
		self.assertEqual(modify.call_args.args, ("we_1",))
		self.assertEqual(modify.call_args.kwargs["enabled_events"], ["payment_intent.canceled"])
		self.assertEqual(
			modify.call_args.kwargs["stripe_version"], "2026-08-26.dahlia"
		)  # per request, pinned

	def test_create_customer_returns_id(self):
		adapter = self.make_adapter()
		with patch.object(stripe.Customer, "create", return_value=frappe._dict(id="cus_new")) as create:
			cid = adapter.create_customer(frappe._dict(name="Team-1", owner_user="a@b.com"))
		self.assertEqual(cid, "cus_new")
		self.assertEqual(create.call_args.kwargs["email"], "a@b.com")

	def test_a_rejected_key_raises_a_gateway_error_the_customer_never_sees(self):
		"""A bad key reaches core billing as GatewayAuthError, and the customer reads a plain message."""
		from central.billing.gateways.base import GatewayAuthError, customer_safe_gateway_errors

		adapter = self.make_adapter()
		err = stripe.error.AuthenticationError("Invalid API Key provided: sk_test_****123")
		with patch.object(stripe.Customer, "create", side_effect=err), self.assertRaises(GatewayAuthError):
			adapter.create_customer(frappe._dict(name="Team-1", owner_user="a@b.com"))

		with (
			patch.object(stripe.SetupIntent, "create", side_effect=err),
			patch.object(frappe, "log_error") as log_error,
			self.assertRaises(frappe.ValidationError) as raised,
			customer_safe_gateway_errors(),
		):
			adapter.setup_payment_method(
				frappe._dict(name="Team-1"), {"customer_id": "cus_1", "currency": "USD"}
			)

		self.assertNotIn("sk_test", str(raised.exception))
		self.assertIn("payment provider", str(raised.exception))
		log_error.assert_called_once()

	def test_a_stripe_outage_asks_the_customer_to_try_again(self):
		from central.billing.gateways.base import customer_safe_gateway_errors

		adapter = self.make_adapter()
		err = stripe.error.APIConnectionError("Network error")
		with (
			patch.object(stripe.PaymentIntent, "create", side_effect=err),
			patch.object(frappe, "log_error"),
			self.assertRaisesRegex(frappe.ValidationError, "Try again in a few minutes"),
			customer_safe_gateway_errors(),
		):
			adapter.create_order(100, "USD", "topup-1")

	def test_an_order_keeps_cents_off_the_callers_amount(self):
		"""create_topup_order spreads these handles over its own major-unit `amount`."""
		adapter = self.make_adapter()
		intent = {"id": "pi_1", "client_secret": "s", "amount": 15000}
		with patch.object(stripe.PaymentIntent, "create", return_value=intent):
			handles = adapter.create_order(150, "USD", "topup-1")
		self.assertNotIn("amount", handles)
		self.assertEqual(handles["amount_in_subunits"], 15000)

	def test_get_mandate_status(self):
		adapter = self.make_adapter()
		with patch.object(stripe.Mandate, "retrieve", return_value=frappe._dict(status="Active")):
			self.assertEqual(adapter.get_mandate_status("mandate_x"), "Active")

	def test_verify_payment_signature_is_unsupported(self):
		adapter = self.make_adapter()
		with self.assertRaises(GatewayUnsupported):
			adapter.verify_payment_signature({})

	# --- real StripeObject normalisation (regression) -----------------------
	# Stripe v15 StripeObjects expose neither .get() nor dict() conversion; the
	# adapter must normalise responses via to_dict(). Earlier tests mock with
	# frappe._dict (which has .get), so they don't catch this — construct_from
	# builds a genuine StripeObject the way the live SDK returns one.

	def test_create_checkout_session_handles_real_stripe_object(self):
		adapter = self.make_adapter()
		session = stripe.checkout.Session.construct_from(
			{"id": "cs_x", "url": "https://checkout.stripe/cs_x"}, "sk_test"
		)
		with patch.object(stripe.checkout.Session, "create", return_value=session):
			out = adapter.create_checkout_session(50.0, "EUR", "rcpt", "https://ok", "https://no")
		self.assertEqual(out["checkout_url"], "https://checkout.stripe/cs_x")
		self.assertEqual(out["session_id"], "cs_x")

	def test_get_checkout_session_normalises_real_stripe_object(self):
		adapter = self.make_adapter()
		session = stripe.checkout.Session.construct_from(
			{
				"id": "cs_x",
				"payment_status": "paid",
				"payment_intent": "pi_x",
				"amount_total": 5000,
				"currency": "eur",
			},
			"sk_test",
		)
		with patch.object(stripe.checkout.Session, "retrieve", return_value=session):
			out = adapter.get_checkout_session("cs_x")
		self.assertEqual(out["payment_status"], "paid")
		self.assertEqual(out["payment_intent"], "pi_x")

	def test_get_transaction_status_handles_real_stripe_object(self):
		adapter = self.make_adapter()
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "succeeded"}, "sk_test")
		with patch.object(stripe.PaymentIntent, "retrieve", return_value=intent):
			self.assertEqual(adapter.get_transaction_status("pi_x"), "succeeded")

	def test_get_payment_intent_normalises_real_stripe_object(self):
		"""confirm_topup reads the full intent (status + amount + currency) to credit
		from what Stripe actually charged, so it must normalise a real StripeObject."""
		adapter = self.make_adapter()
		intent = stripe.PaymentIntent.construct_from(
			{"id": "pi_x", "status": "succeeded", "amount_received": 5000, "currency": "eur"}, "sk_test"
		)
		with patch.object(stripe.PaymentIntent, "retrieve", return_value=intent):
			out = adapter.get_payment_intent("pi_x")
		self.assertEqual(out["status"], "succeeded")
		self.assertEqual(out["amount_received"], 5000)
		self.assertEqual(out["currency"], "eur")

	def test_a_refused_setup_reads_back_the_bank_reason(self):
		adapter = self.make_adapter()
		intent = stripe.SetupIntent.construct_from(
			{
				"id": "seti_x",
				"status": "requires_payment_method",
				"last_setup_error": {
					"type": "card_error",
					"code": "card_declined",
					"decline_code": "generic_decline",
				},
			},
			"sk_test",
		)
		with patch.object(stripe.SetupIntent, "retrieve", return_value=intent):
			out = adapter.read_saved_card("seti_x")
		self.assertEqual(
			out, {"setup_error": {"failure_code": "card_declined", "decline_code": "generic_decline"}}
		)


class TestIndiaCardMandate(IntegrationTestCase):
	"""Stripe India registers the mandate an Indian recurring card debit needs, and
	every later debit quotes it (ADR 0022)."""

	def setUp(self):
		self.gateway = make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		self.adapter = StripeAdapter(self.gateway)

	def _setup_intent(self, **setup_data):
		intent = stripe.SetupIntent.construct_from({"id": "seti_x", "client_secret": "seti_x_sec"}, "sk")
		with patch.object(stripe.SetupIntent, "create", return_value=intent) as create:
			self.adapter.setup_payment_method(frappe._dict(name="t"), {"customer_id": "cus_x", **setup_data})
		return create.call_args.kwargs

	def test_an_inr_card_registers_a_mandate(self):
		params = self._setup_intent(currency="INR", max_amount=15000)
		options = params["payment_method_options"]["card"]["mandate_options"]
		self.assertEqual(options["amount"], 1500000)  # paise
		self.assertEqual(options["amount_type"], "maximum")
		self.assertEqual(options["currency"], "inr")
		self.assertEqual(options["supported_types"], ["india"])
		# Usage-based billing has no fixed amount and no fixed date.
		self.assertEqual(options["interval"], "sporadic")

	def test_the_registered_maximum_is_the_ceiling_we_enforce(self):
		"""The customer consents to one number and the bank enforces it, so it must be
		the number the charge path checks — not a second one that could drift."""
		params = self._setup_intent(currency="INR", max_amount=8000)
		self.assertEqual(params["payment_method_options"]["card"]["mandate_options"]["amount"], 800000)

	def test_a_usd_card_asks_for_no_mandate(self):
		params = self._setup_intent(currency="USD", max_amount=None)
		self.assertNotIn("payment_method_options", params)

	def test_an_off_session_debit_quotes_the_mandate(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "succeeded"}, "sk")
		method = frappe._dict(gateway_method_id="pm_x", gateway_mandate_id="mandate_x", team="t")
		with patch.object(stripe.PaymentIntent, "create", return_value=intent) as create:
			self.adapter.charge(
				frappe._dict(name="INV-1", amount=1000, currency="INR", customer_id="cus_x", team="t"),
				method,
				"key-1",
			)
		self.assertEqual(create.call_args.kwargs["mandate"], "mandate_x")
		self.assertTrue(create.call_args.kwargs["off_session"])

	def test_a_card_with_no_mandate_sends_none(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "succeeded"}, "sk")
		method = frappe._dict(gateway_method_id="pm_x", team="t")
		with patch.object(stripe.PaymentIntent, "create", return_value=intent) as create:
			self.adapter.charge(
				frappe._dict(name="INV-1", amount=50, currency="USD", customer_id="cus_x", team="t"),
				method,
				"key-2",
			)
		self.assertNotIn("mandate", create.call_args.kwargs)

	def test_a_charge_fails_cleanly_when_stripe_rejects_the_mandate(self):
		method = frappe._dict(gateway_method_id="pm_x", gateway_mandate_id="mandate_x", team="t")
		error = stripe.error.InvalidRequestError(
			"The parameter `mandate` is not provided or invalid.", param="mandate"
		)
		with patch.object(stripe.PaymentIntent, "create", side_effect=error):
			result = self.adapter.charge(
				frappe._dict(name="INV-1", amount=1000, currency="INR", customer_id="cus_x", team="t"),
				method,
				"key-3",
			)
		self.assertFalse(result.success)
		self.assertEqual(result.status, "Failed")

	def test_a_reused_charge_key_is_an_unknown_outcome_not_a_decline(self):
		method = frappe._dict(gateway_method_id="pm_x", team="t")
		error = stripe.error.IdempotencyError(
			"Keys for idempotent requests can only be used with the same parameters"
		)
		with patch.object(stripe.PaymentIntent, "create", side_effect=error):
			with self.assertRaises(GatewayTimeout):
				self.adapter.charge(
					frappe._dict(name="INV-1", amount=50, currency="USD", customer_id="cus_x", team="t"),
					method,
					"key-4",
				)

	def test_a_mandate_card_is_checked_by_its_mandate_not_a_charge(self):
		method = frappe._dict(
			gateway_method_id="pm_x", gateway_mandate_id="mandate_x", gateway_customer_id="cus_x", team="t"
		)
		with (
			patch.object(stripe.Mandate, "retrieve", return_value=frappe._dict(status="active")),
			patch.object(stripe.PaymentIntent, "create") as create,
		):
			validated = self.adapter.validate_payment_method(method)
		create.assert_not_called()
		self.assertTrue(validated.success)

	def test_an_inactive_mandate_fails_the_card(self):
		method = frappe._dict(gateway_method_id="pm_x", gateway_mandate_id="mandate_x", team="t")
		with patch.object(stripe.Mandate, "retrieve", return_value=frappe._dict(status="inactive")):
			validated = self.adapter.validate_payment_method(method)
		self.assertFalse(validated.success)
		self.assertEqual(validated.failure_code, "mandate_inactive")

	def test_the_check_charge_is_keyed_on_the_method_and_refunded(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "succeeded"}, "sk")
		method = frappe._dict(name="pm-doc", gateway_method_id="pm_x", gateway_customer_id="cus_x", team="t")
		with (
			patch.object(stripe.PaymentIntent, "create", return_value=intent) as create,
			patch.object(stripe.Refund, "create") as refund,
		):
			validated = self.adapter.validate_payment_method(method)
		key = create.call_args.kwargs["idempotency_key"]
		self.assertTrue(key.endswith(":card-check:pm-doc"))
		self.assertEqual(refund.call_args.kwargs["idempotency_key"], f"{key}:refund")
		self.assertTrue(validated.success)

	def test_a_check_charge_waiting_on_the_customer_is_cancelled(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "requires_action"}, "sk")
		method = frappe._dict(name="pm-doc", gateway_method_id="pm_x", team="t")
		with (
			patch.object(stripe.PaymentIntent, "create", return_value=intent),
			patch.object(stripe.PaymentIntent, "cancel") as cancel,
		):
			validated = self.adapter.validate_payment_method(method)
		cancel.assert_called_once()
		self.assertEqual(cancel.call_args.args, ("pi_x",))
		self.assertFalse(validated.success)
		self.assertEqual(validated.failure_code, "check_unfinished")

	def test_a_processing_check_charge_is_reported_not_cancelled(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "processing"}, "sk")
		method = frappe._dict(name="pm-doc", gateway_method_id="pm_x", team="t")
		with (
			patch.object(stripe.PaymentIntent, "create", return_value=intent),
			patch.object(stripe.PaymentIntent, "cancel") as cancel,
			patch.object(frappe, "log_error") as log_error,
		):
			validated = self.adapter.validate_payment_method(method)
		cancel.assert_not_called()
		log_error.assert_called_once()
		self.assertFalse(validated.success)
		self.assertEqual(validated.failure_code, "check_unfinished")

	def test_a_failed_check_refund_still_proves_the_card(self):
		intent = stripe.PaymentIntent.construct_from({"id": "pi_x", "status": "succeeded"}, "sk")
		method = frappe._dict(name="pm-doc", gateway_method_id="pm_x", team="t")
		with (
			patch.object(stripe.PaymentIntent, "create", return_value=intent),
			patch.object(stripe.Refund, "create", side_effect=stripe.error.APIError("down")),
			patch.object(frappe, "log_error") as log_error,
		):
			validated = self.adapter.validate_payment_method(method)
		self.assertTrue(validated.success)
		log_error.assert_called_once()

	def test_validation_fails_cleanly_when_stripe_rejects_a_missing_mandate(self):
		method = frappe._dict(gateway_method_id="pm_x", gateway_customer_id="cus_x", team="t")
		error = stripe.error.InvalidRequestError(
			"The parameter `mandate` is not provided or invalid.", param="mandate"
		)
		with patch.object(stripe.PaymentIntent, "create", side_effect=error):
			validated = self.adapter.validate_payment_method(method)
		self.assertFalse(validated.success)
		self.assertIn("mandate", validated.failure_reason)

	def test_a_declined_card_check_carries_the_decline_code(self):
		method = frappe._dict(gateway_method_id="pm_x", gateway_customer_id="cus_x", team="t")
		error = stripe.error.CardError(
			"Your card has insufficient funds.",
			param=None,
			code="card_declined",
			json_body={"error": {"code": "card_declined", "decline_code": "insufficient_funds"}},
		)
		with patch.object(stripe.PaymentIntent, "create", side_effect=error):
			validated = self.adapter.validate_payment_method(method)
		self.assertEqual(
			(validated.failure_code, validated.decline_code), ("card_declined", "insufficient_funds")
		)
