# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.gateways.base import GatewayAuthError, GatewayUnsupported
from central.billing.gateways.stripe_adapter import StripeAdapter
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def _new_gateway(name="GW-Setup-Test", **overrides):
	"""Build (unsaved) a Stripe gateway with setup validation forced on."""
	if frappe.db.exists("Payment Gateway", name):
		frappe.delete_doc("Payment Gateway", name, force=True)
	values = {
		"doctype": "Payment Gateway", "__newname": name, "title": "Stripe (Setup)",
		"adapter_key": "Stripe",
		"currencies": [{"currency": "USD", "is_default": 1}],
		"api_secret": "sk_live_xyz",
		**overrides,
	}
	doc = frappe.get_doc(values)
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
				doc.insert(ignore_permissions=True)

	def test_valid_keys_stamp_validated_at_and_autofill_webhook(self):
		doc = _new_gateway()
		identity = {"account_id": "acct_1", "currency": "USD"}
		registered = {"endpoint_id": "we_1", "secret": "whsec_auto"}
		with (
			patch.object(StripeAdapter, "validate_credentials", return_value=identity),
			patch.object(StripeAdapter, "register_webhook", return_value=registered) as reg,
		):
			doc.insert(ignore_permissions=True)

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
				StripeAdapter, "validate_credentials",
				return_value={"account_id": "a", "currency": "EUR"},
			),
			patch.object(
				StripeAdapter, "register_webhook",
				return_value={"endpoint_id": "we_x", "secret": "whsec_x"},
			),
		):
			doc.insert(ignore_permissions=True)
		self.assertTrue(doc.credentials_validated_at)

	def test_cannot_enable_without_validated_credentials(self):
		# No keys entered → nothing to validate, but is_enabled is on.
		doc = _new_gateway(api_secret="", is_enabled=1)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_manual_secret_kept_when_gateway_cannot_self_register(self):
		doc = _new_gateway(webhook_secret="whsec_manual")
		with (
			patch.object(
				StripeAdapter, "validate_credentials",
				return_value={"account_id": "a", "currency": "USD"},
			),
			patch.object(StripeAdapter, "register_webhook", side_effect=GatewayUnsupported("nope")),
		):
			doc.insert(ignore_permissions=True)
		self.assertFalse(doc.webhook_endpoint_id)
		self.assertEqual(doc.get_password("webhook_secret"), "whsec_manual")

	def test_unrelated_edit_does_not_revalidate(self):
		doc = _new_gateway()
		with (
			patch.object(
				StripeAdapter, "validate_credentials",
				return_value={"account_id": "a", "currency": "USD"},
			),
			patch.object(StripeAdapter, "register_webhook", return_value={"endpoint_id": "we", "secret": "s"}),
		):
			doc.insert(ignore_permissions=True)

		# Edit a non-secret field; the secret field now holds the '*****' mask.
		doc.title = "Stripe (Setup) updated"
		with patch.object(StripeAdapter, "validate_credentials") as vc:
			doc.save(ignore_permissions=True)
		vc.assert_not_called()


class TestGatewayCredentialResolution(IntegrationTestCase):
	"""GatewayAdapter.get_credential lets live keys live in common_site_config.json
	(overriding the Payment Gateway doc) while falling back to the doc otherwise."""

	def test_falls_back_to_doc_when_not_in_site_config(self):
		from central.billing.gateways.registry import get_adapter

		gw = make_stripe_gateway("GW-Cred-Test")
		adapter = get_adapter(gw)
		# stripe_webhook_secret is not in this site's config -> read off the doc.
		self.assertNotIn("stripe_webhook_secret", frappe.conf)
		self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_test_123")

	def test_site_config_key_overrides_the_doc(self):
		from central.billing.gateways.registry import get_adapter

		gw = make_stripe_gateway("GW-Cred-Test2")
		adapter = get_adapter(gw)
		with patch.dict(frappe.local.conf, {"stripe_webhook_secret": "whsec_from_conf"}):
			self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_from_conf")
		# Override gone -> doc value again.
		self.assertEqual(adapter.get_credential("webhook_secret"), "whsec_test_123")
