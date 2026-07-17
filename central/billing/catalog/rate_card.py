# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The composed-config component rate card (ADR 0009).

A custom compute config is priced à la carte — `Σ(quantity × per-resource rate)` —
so the three compute primitives (`Compute`, `Memory`, `Disk`) must each carry a
per-unit rate. Those rates are ordinary `Catalog Rate` rows with
`priced_doctype = Resource Type`; this module seeds a starter card (global default
per shipped currency) so a composed config can be priced end-to-end on a fresh
install. Admins re-price a component through `update_component_rate`.

Idempotent: a component rate is seeded only when absent, so re-running never
clobbers an admin's edit.
"""

import frappe

from central.billing.catalog.pricing import set_catalog_rate

# The priceable compute primitives and the unit each rate is quoted in. A composed
# config is built only from these three; Transfer is a metered overage, not a
# slider dimension.
COMPONENT_UNITS = {"Compute": "vCPU", "Memory": "GB", "Disk": "GB"}

# Starter global (blank-cluster) rates per shipped currency, in major Currency
# units per unit per month. Deliberately round so a hand-summed config is easy to
# verify; admins tune them per region afterwards. We bill only in INR and USD for
# now, so those are the only two cards seeded.
STARTER_RATE_CARD = {
	"INR": {"Compute": 500, "Memory": 250, "Disk": 10},
	"USD": {"Compute": 6, "Memory": 3, "Disk": 0.12},
}


def ensure_component_rate_card():
	"""Seed the starter component rate card if absent. Safe to call repeatedly."""
	for currency, rates in STARTER_RATE_CARD.items():
		for resource_type, rate in rates.items():
			if not _has_rate(resource_type, currency):
				set_catalog_rate("Resource Type", resource_type, currency, rate)


def _has_rate(resource_type: str, currency: str, cluster: str | None = None) -> bool:
	return bool(
		frappe.db.exists(
			"Catalog Rate",
			{
				"priced_doctype": "Resource Type",
				"priced_for": resource_type,
				"currency": currency,
				"cluster": cluster,
			},
		)
	)
