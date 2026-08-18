# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a gateway may do in one currency (ADR 0022).

The silent-debit ceiling is a property of *(gateway, currency)*, not of the
provider. Stripe pulls any amount in USD and at most ₹15,000 in INR, because the
RBI ceiling follows the currency and the merchant's country rather than the brand
on the rail. A per-adapter scalar cannot say that, so the ceiling lives on the
`Payment Gateway Currency` row and this module is the only place that reads it.

Amounts here are floats in MAJOR units (₹, $), like all money in billing.
"""

import frappe

# The RBI off-session ceiling for our merchant category. It binds every gateway
# settling INR, ours included, so it is a floor on configuration rather than a
# default an admin may raise.
INR_SILENT_CEILING = 15000.0


def currency_row(gateway: str, currency: str) -> frappe._dict | None:
	"""The gateway's row for this currency, or None if it does not settle it."""
	rows = frappe.get_all(
		"Payment Gateway Currency",
		filters={"parent": gateway, "parenttype": "Payment Gateway", "currency": currency},
		fields=["max_silent_charge", "requires_predebit_notice"],
		limit=1,
	)
	return rows[0] if rows else None


def silent_charge_ceiling(gateway: str, currency: str) -> float | None:
	"""Largest amount `gateway` may pull off-session in `currency`; None = no ceiling.

	The configured ceiling wins where there is one, and the regulatory ceiling for
	the currency answers where there isn't. So a half-configured gateway, or one
	with no row for the currency at all, still cannot silently pull ₹50,000 — the
	RBI line holds whether or not an admin has filled the field in.
	"""
	row = currency_row(gateway, currency)
	configured = frappe.utils.flt(row.max_silent_charge) if row else 0.0
	return configured or regulatory_ceiling(currency)


def requires_predebit_notice(gateway: str, currency: str) -> bool:
	"""Whether every off-session debit on this rail is preceded by a notice."""
	row = currency_row(gateway, currency)
	return bool(row and row.requires_predebit_notice)


# Gateways that issue the RBI pre-debit notification themselves and hold the debit
# for their own window. We must not run ours on top of theirs.
SELF_NOTIFYING_GATEWAYS = ("Stripe",)


def self_notifies(gateway: str) -> bool:
	"""Whether this gateway sends the pre-debit notice and holds the charge itself."""
	return gateway in SELF_NOTIFYING_GATEWAYS


def is_regulated_currency(currency: str) -> bool:
	"""Currencies whose silent-debit ceiling is set by regulation, not by us."""
	return currency == "INR"


def regulatory_ceiling(currency: str) -> float | None:
	"""The ceiling the law imposes on this currency, whatever the gateway."""
	return INR_SILENT_CEILING if is_regulated_currency(currency) else None
