# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Resolve a Payment Gateway config row to its GatewayAdapter implementation."""

import frappe

from central.billing.gateways.base import GatewayAdapter


def get_adapter(gateway) -> GatewayAdapter:
	"""Return the adapter instance for a Payment Gateway doc, keyed by adapter_key."""
	from central.billing.gateways.paypal_adapter import PayPalAdapter
	from central.billing.gateways.razorpay_adapter import RazorpayAdapter
	from central.billing.gateways.stripe_adapter import StripeAdapter

	adapters = {
		"stripe": StripeAdapter,
		"razorpay": RazorpayAdapter,
		"paypal": PayPalAdapter,
	}

	adapter_class = adapters.get(gateway.adapter_key)
	if not adapter_class:
		frappe.throw(f"No GatewayAdapter registered for adapter_key '{gateway.adapter_key}'")

	return adapter_class(gateway)
