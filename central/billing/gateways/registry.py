# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resolve a Payment Gateway config row to its GatewayAdapter implementation."""

import frappe
from frappe import _

from central.billing.gateways.base import GatewayAdapter


class GatewayNotFound(frappe.ValidationError):
	"""No enabled Payment Gateway is configured as the default for the given currency."""


def resolve_gateway_for_currency(currency: str) -> str:
	"""Return the name of the enabled Payment Gateway whose currencies child table
	has an is_default row for `currency`. Raises GatewayNotFound if none configured.

	Every default row for the currency is considered, not just the first: the
	uniqueness rule only clears the flag on *enabled* gateways, so a gateway that was
	switched off keeps its default flag and would otherwise shadow the live one.
	"""
	names = frappe.get_all(
		"Payment Gateway Currency",
		filters={"currency": currency, "is_default": 1},
		pluck="parent",
	)
	for name in names:
		if frappe.db.get_value("Payment Gateway", name, "is_enabled"):
			return name
	raise GatewayNotFound(f"No enabled payment gateway is configured as the default for {currency}.")


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

	PayPal is a directly-settled standalone gateway (ADR 0007, superseding ADR 0005):
	its own merchant account settles us, so top-ups carry native PayPal capture ids
	that the reconciliation job (#21) matches against PayPal's ledger."""
	from central.billing.gateways.paypal_adapter import PayPalAdapter
	from central.billing.gateways.razorpay_adapter import RazorpayAdapter
	from central.billing.gateways.stripe_adapter import StripeAdapter

	adapters = {
		"Stripe": StripeAdapter,
		"Razorpay": RazorpayAdapter,
		"Paypal": PayPalAdapter,
	}

	adapter_class = adapters.get(gateway.adapter_key)
	if not adapter_class:
		frappe.throw(_("No GatewayAdapter registered for adapter_key '{0}'").format(gateway.adapter_key))

	return adapter_class(gateway)
