# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.gateways.base import (
	GatewayAuthError,
	GatewayError,
	GatewayTimeout,
	GatewayUnsupported,
	WebhookNotFound,
)
from central.billing.gateways.stripe_adapter import STRIPE_WEBHOOK_EVENTS, StripeAdapter
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

_CONTROLLER = "central.billing.doctype.payment_gateway.payment_gateway"


def _new_gateway(**overrides):
	"""The Stripe gateway with freshly-typed keys and setup validation forced on.

	Returned unsaved: these tests assert on what `save()` does. The row itself always
	exists (one per adapter, seeded), so this configures rather than creates."""
	from central.billing.gateways.setup import ensure_gateway_records

	ensure_gateway_records()
	doc = frappe.get_doc("Payment Gateway", "Stripe")
	doc.currencies = []
	doc.append("currencies", {"currency": "USD", "is_default": 1})
	doc.update(
		{
			"api_secret": "sk_live_xyz",
			"webhook_secret": None,
			"webhook_endpoint_id": None,
			"credentials_validated_at": None,
			"is_enabled": 1,
			**overrides,
		}
	)
	doc.flags.force_credential_validation = True
	return doc


class TestPaymentGatewaySecrets(IntegrationTestCase):
	def test_secrets_are_encrypted_at_rest_but_recoverable(self):
		gw = make_stripe_gateway()

		# Recoverable by the adapter via get_password...
		self.assertEqual(gw.get_password("webhook_secret"), "whsec_test_123")

		# ...but never stored in plaintext.
		stored = frappe.db.get_value("Payment Gateway", gw.name, "webhook_secret")
		self.assertNotEqual(stored, "whsec_test_123")

	def test_password_fields_are_not_exposed_in_document_dict(self):
		gw = make_stripe_gateway()
		# Password fieldtype values are not serialised as plaintext in as_dict.
		self.assertNotEqual(gw.as_dict().get("api_secret"), "sk_test_123")


class TestGatewaySetupValidation(IntegrationTestCase):
	"""Setup validates the keys and auto-fills the webhook secret (issue #40)."""

	def test_invalid_keys_reject_the_save(self):
		doc = _new_gateway(is_enabled=0)
		with patch.object(StripeAdapter, "validate_credentials", side_effect=GatewayAuthError("bad key")):
			with self.assertRaises(frappe.ValidationError):
				doc.save(ignore_permissions=True)

	def test_valid_keys_stamp_validated_at_and_autofill_webhook(self):
		doc = _new_gateway()
		identity = {"account_id": "acct_1", "currency": "USD"}
		registered = {"endpoint_id": "we_1", "secret": "whsec_auto"}
		with (
			# The test site is *.local, which the controller (rightly) refuses to
			# register a callback for — stand in a publicly reachable host so the
			# registration path this test is about actually runs.
			patch(f"{_CONTROLLER}.get_url", return_value="https://billing.example.com"),
			patch.object(StripeAdapter, "validate_credentials", return_value=identity),
			patch.object(StripeAdapter, "register_webhook", return_value=registered) as reg,
		):
			doc.save(ignore_permissions=True)

		self.assertTrue(doc.credentials_validated_at)
		self.assertEqual(doc.webhook_endpoint_id, "we_1")
		self.assertEqual(doc.get_password("webhook_secret"), "whsec_auto")
		# Registered against this site's gateway-specific callback route.
		self.assertTrue(
			reg.call_args.args[0].endswith("/api/method/central.billing.payments.webhooks.stripe")
		)

	def test_account_currency_difference_does_not_block_setup(self):
		# A single gateway account settles many presentment currencies — a USD
		# Stripe account still accepts EUR/INR charges — so the account's default
		# currency differing from the gateway's configured currency must NOT
		# reject setup. The configured currency is the team's transaction
		# currency, not a constraint on what the account can accept.
		doc = _new_gateway()  # configured USD
		with (
			patch.object(
				StripeAdapter,
				"validate_credentials",
				return_value={"account_id": "a", "currency": "EUR"},
			),
			patch.object(
				StripeAdapter,
				"register_webhook",
				return_value={"endpoint_id": "we_x", "secret": "whsec_x"},
			),
		):
			doc.save(ignore_permissions=True)
		self.assertTrue(doc.credentials_validated_at)

	def test_cannot_enable_without_validated_credentials(self):
		# No keys entered → nothing to validate, but is_enabled is on.
		doc = _new_gateway(api_secret="", is_enabled=1)
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_manual_secret_kept_when_gateway_cannot_self_register(self):
		doc = _new_gateway(webhook_secret="whsec_manual")
		with (
			patch.object(
				StripeAdapter,
				"validate_credentials",
				return_value={"account_id": "a", "currency": "USD"},
			),
			patch.object(StripeAdapter, "register_webhook", side_effect=GatewayUnsupported("nope")),
		):
			doc.save(ignore_permissions=True)
		self.assertFalse(doc.webhook_endpoint_id)
		self.assertEqual(doc.get_password("webhook_secret"), "whsec_manual")

	def test_unrelated_edit_does_not_revalidate(self):
		doc = _new_gateway()
		with (
			patch.object(
				StripeAdapter,
				"validate_credentials",
				return_value={"account_id": "a", "currency": "USD"},
			),
			patch.object(
				StripeAdapter, "register_webhook", return_value={"endpoint_id": "we", "secret": "s"}
			),
		):
			doc.save(ignore_permissions=True)

		# Edit a non-secret field; the secret field now holds the '*****' mask.
		doc.supports_mandates = 1
		with patch.object(StripeAdapter, "validate_credentials") as vc:
			doc.save(ignore_permissions=True)
		vc.assert_not_called()


class TestGatewayCredentialResolution(IntegrationTestCase):
	"""GatewayAdapter.get_credential lets live keys live in common_site_config.json
	(overriding the Payment Gateway doc) while falling back to the doc otherwise."""

	def test_falls_back_to_doc_when_not_in_site_config(self):
		from central.billing.gateways.registry import get_adapter

		gw = make_stripe_gateway()
		adapter = get_adapter(gw)
		# stripe_webhook_secret is not in this site's config -> read off the doc.
		self.assertNotIn("stripe_webhook_secret", frappe.conf)
		self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_test_123")

	def test_site_config_key_overrides_the_doc(self):
		from central.billing.gateways.registry import get_adapter

		gw = make_stripe_gateway()
		adapter = get_adapter(gw)
		with patch.dict(frappe.local.conf, {"stripe_webhook_secret": "whsec_from_conf"}):
			self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_from_conf")
		# Override gone -> doc value again.
		self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_test_123")


_IDENTITY = {"account_id": "acct_1", "currency": "USD"}


def _webhook(events, url="https://billing.example.com/api/method/central.billing.payments.webhooks.stripe"):
	return {"url": url, "is_active": True, "events": list(events)}


class TestWebhookOnKeyChange(IntegrationTestCase):
	"""New keys keep the endpoint when they can see it, and register one when they cannot."""

	def setUp(self):
		patch(f"{_CONTROLLER}.get_url", return_value="https://billing.example.com").start()
		patch.object(StripeAdapter, "validate_credentials", return_value=_IDENTITY).start()
		self.register = patch.object(
			StripeAdapter, "register_webhook", return_value={"endpoint_id": "we_new", "secret": "whsec_new"}
		).start()
		self.update = patch.object(StripeAdapter, "update_webhook_events").start()
		self.addCleanup(patch.stopall)
		self.doc = _new_gateway(webhook_endpoint_id="we_1", webhook_secret="whsec_old")

	def test_same_account_keys_subscribe_the_missing_events(self):
		with patch.object(StripeAdapter, "get_webhook", return_value=_webhook(["payment_intent.succeeded"])):
			self.doc.save(ignore_permissions=True)

		self.update.assert_called_once()
		self.assertEqual(self.update.call_args.args[2], list(STRIPE_WEBHOOK_EVENTS))
		self.register.assert_not_called()
		self.assertEqual(self.doc.webhook_endpoint_id, "we_1")
		self.assertEqual(self.doc.get_password("webhook_secret"), "whsec_old")
		self.assertEqual({row.state for row in self.doc.webhook_events}, {"OK"})

	def test_same_account_keys_with_every_event_change_nothing_at_the_gateway(self):
		with patch.object(StripeAdapter, "get_webhook", return_value=_webhook(STRIPE_WEBHOOK_EVENTS)):
			self.doc.save(ignore_permissions=True)

		self.update.assert_not_called()
		self.register.assert_not_called()

	def test_keys_for_another_account_register_a_new_endpoint(self):
		with patch.object(StripeAdapter, "get_webhook", side_effect=WebhookNotFound("we_1")):
			self.doc.save(ignore_permissions=True)

		self.register.assert_called_once()
		self.assertEqual(self.doc.webhook_endpoint_id, "we_new")
		self.assertEqual(self.doc.get_password("webhook_secret"), "whsec_new")

	def test_a_failed_webhook_read_does_not_block_saving_the_keys(self):
		with patch.object(StripeAdapter, "get_webhook", side_effect=GatewayTimeout("slow")):
			self.doc.save(ignore_permissions=True)

		self.assertTrue(self.doc.credentials_validated_at)
		self.assertEqual(self.doc.webhook_endpoint_id, "we_1")
		self.register.assert_not_called()


class TestWebhookEventActions(IntegrationTestCase):
	"""Pull lists what the gateway sends; Update subscribes to what Central needs."""

	def setUp(self):
		make_stripe_gateway()
		frappe.db.set_value("Payment Gateway", "Stripe", "webhook_endpoint_id", "we_1")
		self.doc = frappe.get_doc("Payment Gateway", "Stripe")

	def test_pull_marks_missing_and_unused_events(self):
		events = ["payment_intent.succeeded", "customer.created"]
		with patch.object(StripeAdapter, "get_webhook", return_value=_webhook(events)):
			report = self.doc.pull_webhook_events()

		states = {row.event_type: row.state for row in self.doc.webhook_events}
		self.assertEqual(states["payment_intent.succeeded"], "OK")
		self.assertEqual(states["customer.created"], "Not Used")
		self.assertEqual(states["payment_intent.canceled"], "Missing")
		self.assertIn("payment_intent.canceled", report["missing"])
		self.assertTrue(self.doc.webhook_events_pulled_at)

	def test_update_subscribes_every_needed_event_and_reads_it_back(self):
		with (
			patch.object(StripeAdapter, "get_webhook", return_value=_webhook(STRIPE_WEBHOOK_EVENTS)),
			patch.object(StripeAdapter, "update_webhook_events") as update,
		):
			report = self.doc.update_webhook_events()

		self.assertEqual(update.call_args.args[2], list(STRIPE_WEBHOOK_EVENTS))
		self.assertEqual(report["missing"], [])

	def test_pull_explains_an_endpoint_from_another_account(self):
		with patch.object(StripeAdapter, "get_webhook", side_effect=WebhookNotFound("we_1")):
			with self.assertRaises(frappe.ValidationError):
				self.doc.pull_webhook_events()


class TestWebhookEventList(IntegrationTestCase):
	"""Every event a handler acts on is one the gateway is asked to send."""

	def test_stripe_subscribes_to_every_event_it_handles(self):
		from central.billing.payments import charges, disputes

		handled = {
			event
			for event in charges._AUTHORISED_EVENTS | charges._SUCCESS_EVENTS | charges._FAILURE_EVENTS
			if event.startswith("payment_intent.")
		} | {event for event in disputes.DISPUTE_EVENTS if event.startswith("charge.")}
		self.assertLessEqual(handled, set(STRIPE_WEBHOOK_EVENTS))

	def test_razorpay_subscribes_to_every_event_it_handles(self):
		from central.billing.gateways.razorpay_adapter import RAZORPAY_WEBHOOK_EVENTS
		from central.billing.payments import charges, disputes

		handled = {
			event
			for event in charges._AUTHORISED_EVENTS | charges._SUCCESS_EVENTS | charges._FAILURE_EVENTS
			if event.startswith("payment.")
		} | {event for event in disputes.DISPUTE_EVENTS if event.startswith("payment.")}
		self.assertLessEqual(handled, set(RAZORPAY_WEBHOOK_EVENTS))

	def test_every_refund_event_is_subscribed_by_a_gateway(self):
		from central.billing.gateways.paypal_adapter import PayPalAdapter
		from central.billing.gateways.razorpay_adapter import RazorpayAdapter
		from central.billing.payments.webhooks import REFUND_EVENTS

		adapters = (StripeAdapter, RazorpayAdapter, PayPalAdapter)
		subscribed = {event for adapter in adapters for event in adapter.webhook_events}
		self.assertLessEqual(set(REFUND_EVENTS), subscribed)


class TestReregisterWebhook(IntegrationTestCase):
	"""Re-register makes a new endpoint and secret, and never loses the current one."""

	def setUp(self):
		make_stripe_gateway()
		frappe.db.set_value("Payment Gateway", "Stripe", "webhook_endpoint_id", "we_old")
		self.doc = frappe.get_doc("Payment Gateway", "Stripe")
		patch.object(StripeAdapter, "validate_credentials", return_value=_IDENTITY).start()
		self.register = patch.object(
			StripeAdapter, "register_webhook", return_value={"endpoint_id": "we_new", "secret": "whsec_new"}
		).start()
		self.addCleanup(patch.stopall)

	def test_reregister_creates_a_new_endpoint_and_secret(self):
		with patch(f"{_CONTROLLER}.get_url", return_value="https://billing.example.com"):
			result = self.doc.revalidate_and_register_webhook()

		self.assertEqual(result, {"registered": True, "webhook_endpoint_id": "we_new", "previous": "we_old"})
		self.assertEqual(frappe.db.get_value("Payment Gateway", "Stripe", "webhook_endpoint_id"), "we_new")
		self.assertEqual(self.doc.get_password("webhook_secret"), "whsec_new")

	def test_a_skipped_registration_keeps_the_current_endpoint(self):
		# The test site is *.local, which no gateway can reach, so registration is skipped.
		result = self.doc.revalidate_and_register_webhook()

		self.assertFalse(result["registered"])
		self.register.assert_not_called()
		self.assertEqual(frappe.db.get_value("Payment Gateway", "Stripe", "webhook_endpoint_id"), "we_old")
		self.assertEqual(self.doc.get_password("webhook_secret"), "whsec_test_123")

	def test_a_gateway_error_is_shown_and_keeps_the_current_endpoint(self):
		self.register.side_effect = GatewayError("url not allowed")
		with patch(f"{_CONTROLLER}.get_url", return_value="https://billing.example.com"):
			with self.assertRaises(frappe.ValidationError):
				self.doc.revalidate_and_register_webhook()

		self.assertEqual(frappe.db.get_value("Payment Gateway", "Stripe", "webhook_endpoint_id"), "we_old")


class TestEnableNeedsAWebhookSecret(IntegrationTestCase):
	def test_a_gateway_without_a_webhook_secret_cannot_be_enabled(self):
		doc = _new_gateway()
		with (
			patch.object(
				StripeAdapter, "validate_credentials", return_value={"account_id": "a", "currency": "USD"}
			),
			patch.object(
				StripeAdapter, "register_webhook", return_value={"endpoint_id": "we", "secret": None}
			),
			patch.object(StripeAdapter, "get_credential", return_value=None),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "secret"):
				doc.save(ignore_permissions=True)

	def test_an_enabled_gateway_without_a_secret_still_takes_an_unrelated_edit(self):
		frappe.db.set_value(
			"Payment Gateway", "Stripe", {"is_enabled": 1, "credentials_validated_at": frappe.utils.now()}
		)
		doc = frappe.get_doc("Payment Gateway", "Stripe")
		doc.flags.force_credential_validation = True
		doc.supports_mandates = 1
		with patch.object(StripeAdapter, "get_credential", return_value=None):
			doc.save(ignore_permissions=True)
