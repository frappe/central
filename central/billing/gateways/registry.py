# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resolve a Payment Gateway config row to its GatewayAdapter implementation."""

import frappe

from central.billing.gateways.base import GatewayAdapter


class GatewayNotFound(frappe.ValidationError):
	"""No enabled Payment Gateway is configured as the default for the given currency."""


def resolve_gateway_for_currency(currency: str) -> str:
	"""Return the name of the enabled Payment Gateway whose currencies child table
	has an is_default row for `currency`. Raises GatewayNotFound if none configured."""
	name = frappe.db.get_value(
		"Payment Gateway Currency",
		{"currency": currency, "is_default": 1},
		"parent",
	)
	if name and frappe.db.get_value("Payment Gateway", name, "is_enabled"):
		return name
	raise GatewayNotFound(
		f"No enabled payment gateway is configured as the default for {currency}."
	)


def supported_currencies() -> list[str]:
	"""Currencies a team can actually be billed in — every currency that an
	enabled Payment Gateway is the default for. These are the only choices the
	billing-profile currency picker offers, so a team can never select a currency
	it can't be charged or topped up in."""
	rows = frappe.get_all(
		"Payment Gateway Currency", filters={"is_default": 1}, fields=["currency", "parent"]
	)
	enabled = set(frappe.get_all("Payment Gateway", {"is_enabled": 1}, pluck="name"))
	return sorted({r.currency for r in rows if r.parent in enabled and r.currency})


def get_adapter(gateway) -> GatewayAdapter:
	"""Return the adapter instance for a Payment Gateway doc, keyed by adapter_key.

	PayPal is intentionally not a standalone adapter (ADR 0005): it's a one-time
	method *inside* Razorpay's international checkout, not a separate gateway."""
	from central.billing.gateways.razorpay_adapter import RazorpayAdapter
	from central.billing.gateways.stripe_adapter import StripeAdapter

	adapters = {
		"Stripe": StripeAdapter,
		"Razorpay": RazorpayAdapter,
	}

	adapter_class = adapters.get(gateway.adapter_key)
	if not adapter_class:
		frappe.throw(f"No GatewayAdapter registered for adapter_key '{gateway.adapter_key}'")

	return adapter_class(gateway)
