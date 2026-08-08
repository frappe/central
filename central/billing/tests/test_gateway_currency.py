# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Tests for multi-currency gateway config — issue #46.

Covers:
- resolve_gateway_for_currency: returns the correct gateway, raises GatewayNotFound
- is_default invariant: saving a row with is_default=True clears it on other gateways
- the roster invariant: exactly one row per adapter, named after it
"""

import frappe

from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency
from central.billing.gateways.setup import adapter_keys, ensure_gateway_records
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import configure_gateway, disable_gateway

ADAPTERS = ("Stripe", "Razorpay", "Paypal")


class GatewayCurrencyTestCase(IntegrationTestCase):
	"""Every gateway starts each test with no currencies and disabled, so a test only
	sees the routing it sets up itself. Rows are never deleted — they are the roster."""

	def setUp(self):
		ensure_gateway_records()
		for adapter_key in ADAPTERS:
			configure_gateway(adapter_key, [], is_enabled=0)


class TestResolveGatewayForCurrency(GatewayCurrencyTestCase):
	def test_returns_gateway_with_is_default_for_currency(self):
		configure_gateway("Stripe", [("USD", 1)], is_enabled=1)
		self.assertEqual(resolve_gateway_for_currency("USD"), "Stripe")

	def test_raises_gateway_not_found_when_none_configured(self):
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("JPY")

	def test_raises_gateway_not_found_when_gateway_disabled(self):
		configure_gateway("Stripe", [("USD", 1)], is_enabled=0)
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("USD")

	def test_raises_gateway_not_found_when_no_is_default_row(self):
		configure_gateway("Stripe", [("USD", 0)], is_enabled=1)
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("USD")

	def test_gateway_with_multiple_currencies(self):
		"""One merchant account settles several currencies — that is what the child
		table is for, and it is why a second row per provider is never needed."""
		configure_gateway("Stripe", [("EUR", 1), ("USD", 1)], is_enabled=1)
		self.assertEqual(resolve_gateway_for_currency("EUR"), "Stripe")
		self.assertEqual(resolve_gateway_for_currency("USD"), "Stripe")


class TestIsDefaultInvariant(GatewayCurrencyTestCase):
	"""Saving is_default=True on one gateway clears the flag on others for the same
	currency. The competition is between providers now, not between rows of one."""

	def test_setting_is_default_clears_previous_default(self):
		configure_gateway("Stripe", [("USD", 1)], is_enabled=1)
		self.assertEqual(resolve_gateway_for_currency("USD"), "Stripe")

		# PayPal now claims the USD default.
		configure_gateway("Paypal", [("USD", 1)], is_enabled=1)
		self.assertEqual(resolve_gateway_for_currency("USD"), "Paypal")

		# Stripe's row should have been cleared.
		row = frappe.db.get_value(
			"Payment Gateway Currency",
			{"parent": "Stripe", "currency": "USD"},
			"is_default",
		)
		self.assertEqual(row, 0)

	def test_different_currencies_do_not_interfere(self):
		configure_gateway("Stripe", [("USD", 1)], is_enabled=1)
		configure_gateway("Razorpay", [("INR", 1)], is_enabled=1)

		# Each owns its currency independently.
		self.assertEqual(resolve_gateway_for_currency("USD"), "Stripe")
		self.assertEqual(resolve_gateway_for_currency("INR"), "Razorpay")

	def test_disabled_gateway_does_not_hold_a_currency_hostage(self):
		configure_gateway("Stripe", [("USD", 1)], is_enabled=1)
		disable_gateway("Stripe")
		configure_gateway("Paypal", [("USD", 1)], is_enabled=1)
		self.assertEqual(resolve_gateway_for_currency("USD"), "Paypal")


class TestGatewayRoster(GatewayCurrencyTestCase):
	"""One row per adapter, named after it — enforced by the primary key, not by a
	validate() hook that a bulk write could skip."""

	def test_a_row_exists_for_every_adapter_and_is_named_after_it(self):
		for adapter_key in adapter_keys():
			self.assertTrue(frappe.db.exists("Payment Gateway", adapter_key))
			self.assertEqual(
				frappe.db.get_value("Payment Gateway", adapter_key, "adapter_key"), adapter_key
			)

	def test_a_second_row_for_the_same_adapter_is_rejected(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({"doctype": "Payment Gateway", "adapter_key": "Stripe"}).insert(
				ignore_permissions=True
			)

	def test_seeding_is_idempotent(self):
		before = frappe.db.count("Payment Gateway")
		ensure_gateway_records()
		self.assertEqual(frappe.db.count("Payment Gateway"), before)

	def test_adapter_cannot_be_repointed_at_another_provider(self):
		"""Every Payment Attempt / Webhook Event links to this row by name, so flipping
		its adapter would re-attribute settled money to a provider that never took it.

		The field is slaved to the name (autoname `field:adapter_key`), so Frappe drops
		the edit on save — renaming is off, which leaves nothing that can change it."""
		gw = frappe.get_doc("Payment Gateway", "Stripe")
		gw.adapter_key = "Razorpay"
		gw.flags.skip_credential_validation = True
		gw.save(ignore_permissions=True)

		self.assertEqual(gw.adapter_key, "Stripe")
		self.assertEqual(frappe.db.get_value("Payment Gateway", "Stripe", "adapter_key"), "Stripe")
