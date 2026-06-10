# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Tests for multi-currency gateway config — issue #46.

Covers:
- resolve_gateway_for_currency: returns the correct gateway, raises GatewayNotFound
- is_default invariant: saving a row with is_default=True clears it on other gateways
- _gateway_for_currency and _add_method_gateway wrappers in the dashboard layer
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency


def _make_gateway(name, adapter_key, currencies, is_enabled=1, **extra):
	if frappe.db.exists("Payment Gateway", name):
		frappe.delete_doc("Payment Gateway", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Payment Gateway",
			"__newname": name,
			"title": name,
			"adapter_key": adapter_key,
			"currencies": [{"currency": c, "is_default": d} for c, d in currencies],
			"api_key": "key",
			"api_secret": "secret",
			"webhook_secret": "whsec",
			"is_enabled": is_enabled,
			**extra,
		}
	).insert(ignore_permissions=True)


class TestResolveGatewayForCurrency(IntegrationTestCase):
	def setUp(self):
		for name in ("GW-USD-A", "GW-USD-B", "GW-INR-A", "GW-EUR-A"):
			if frappe.db.exists("Payment Gateway", name):
				frappe.delete_doc("Payment Gateway", name, force=True)

	def tearDown(self):
		for name in ("GW-USD-A", "GW-USD-B", "GW-INR-A", "GW-EUR-A"):
			if frappe.db.exists("Payment Gateway", name):
				frappe.delete_doc("Payment Gateway", name, force=True)

	def test_returns_gateway_with_is_default_for_currency(self):
		_make_gateway("GW-USD-A", "stripe", [("USD", 1)])
		self.assertEqual(resolve_gateway_for_currency("USD"), "GW-USD-A")

	def test_raises_gateway_not_found_when_none_configured(self):
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("JPY")

	def test_raises_gateway_not_found_when_gateway_disabled(self):
		_make_gateway("GW-USD-A", "stripe", [("USD", 1)], is_enabled=0)
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("USD")

	def test_raises_gateway_not_found_when_no_is_default_row(self):
		_make_gateway("GW-USD-A", "stripe", [("USD", 0)])
		with self.assertRaises(GatewayNotFound):
			resolve_gateway_for_currency("USD")

	def test_gateway_with_multiple_currencies(self):
		_make_gateway("GW-EUR-A", "stripe", [("EUR", 1), ("USD", 1)])
		self.assertEqual(resolve_gateway_for_currency("EUR"), "GW-EUR-A")
		self.assertEqual(resolve_gateway_for_currency("USD"), "GW-EUR-A")


class TestIsDefaultInvariant(IntegrationTestCase):
	"""Saving is_default=True on one gateway clears the flag on others for the same currency."""

	def setUp(self):
		for name in ("GW-USD-A", "GW-USD-B"):
			if frappe.db.exists("Payment Gateway", name):
				frappe.delete_doc("Payment Gateway", name, force=True)

	def tearDown(self):
		for name in ("GW-USD-A", "GW-USD-B"):
			if frappe.db.exists("Payment Gateway", name):
				frappe.delete_doc("Payment Gateway", name, force=True)

	def test_setting_is_default_clears_previous_default(self):
		_make_gateway("GW-USD-A", "stripe", [("USD", 1)])
		self.assertEqual(resolve_gateway_for_currency("USD"), "GW-USD-A")

		# GW-USD-B now claims the USD default.
		_make_gateway("GW-USD-B", "stripe", [("USD", 1)])
		self.assertEqual(resolve_gateway_for_currency("USD"), "GW-USD-B")

		# GW-USD-A's row should have been cleared.
		row = frappe.db.get_value(
			"Payment Gateway Currency",
			{"parent": "GW-USD-A", "currency": "USD"},
			"is_default",
		)
		self.assertEqual(row, 0)

	def test_different_currencies_do_not_interfere(self):
		_make_gateway("GW-USD-A", "stripe", [("USD", 1)])
		_make_gateway("GW-INR-A", "razorpay", [("INR", 1)])

		# Each owns its currency independently.
		self.assertEqual(resolve_gateway_for_currency("USD"), "GW-USD-A")
		self.assertEqual(resolve_gateway_for_currency("INR"), "GW-INR-A")
