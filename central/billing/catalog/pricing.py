# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rate resolution — region x currency.

A rate is resolved for a team's billing currency and the resource's cluster: the
most-specific region match wins, falling back to the global (blank-cluster) row.

Rates live in one standalone `Catalog Rate` DocType (ERPNext `Item Price` style),
linked to a Plan via a Dynamic Link (`priced_doctype` + `priced_for`). The rate is
the flat price for a fixed bundle and the per-unit price for a metered
single-resource Plan (ADR 0008).
"""

from contextlib import contextmanager
from contextvars import ContextVar

import frappe

# A projection asking "what if we raised this price". Every rate resolution in the
# module comes through `get_catalog_rates`, so overriding here reaches plan rates, the
# component rate card and live-priced metered plans alike — without any of them
# learning that a simulator exists.
#
# It changes what is *read*. No Catalog Rate row is touched, which is what makes the
# question safe to ask against production.
_rate_overrides: ContextVar[tuple] = ContextVar("catalog_rate_overrides", default=())


@contextmanager
def overridden_rates(overrides):
	"""Read catalog rates as if these were published, for this block only.

	Each override names what it reprices — `priced_doctype` and `priced_for`, optionally
	narrowed to a `cluster` and `currency` — and either a flat `rate` or a `percent`
	change applied to whatever is configured.
	"""
	token = _rate_overrides.set(tuple(overrides or ()))
	try:
		yield
	finally:
		_rate_overrides.reset(token)


def active_rate_overrides() -> tuple:
	"""What is currently being pretended about prices, for showing on the output."""
	return _rate_overrides.get()


def _apply_overrides(priced_doctype: str, priced_for: str, rows: list) -> list:
	"""Rewrite the rows a projection should see. Returns the rows unchanged when idle."""
	overrides = _rate_overrides.get()
	if not overrides:
		return rows

	for override in overrides:
		if override.get("priced_doctype") != priced_doctype:
			continue
		if override.get("priced_for") and override["priced_for"] != priced_for:
			continue
		for row in rows:
			if override.get("cluster") and row.cluster != override["cluster"]:
				continue
			if override.get("currency") and row.currency != override["currency"]:
				continue
			if override.get("rate") is not None:
				row.rate = frappe.utils.flt(override["rate"])
			elif override.get("percent"):
				row.rate = frappe.utils.flt(
					frappe.utils.flt(row.rate) * (1 + frappe.utils.flt(override["percent"]) / 100.0), 6
				)
	return rows


def get_catalog_rates(priced_doctype: str, priced_for: str) -> list:
	"""All `Catalog Rate` rows (cluster/currency/rate) for one priced plan."""
	rows = frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": priced_doctype, "priced_for": priced_for},
		fields=["cluster", "currency", "rate"],
	)
	return _apply_overrides(priced_doctype, priced_for, rows)


def set_catalog_rates(priced_doctype: str, priced_for: str, rates) -> None:
	"""Replace every `Catalog Rate` for a plan with the given rows.

	`rates`: iterable of dicts with `cluster` (optional), `currency`, `rate`.
	Used by seeds and tests where rates used to be passed as a child table.
	"""
	for existing in frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": priced_doctype, "priced_for": priced_for},
		pluck="name",
	):
		frappe.delete_doc("Catalog Rate", existing, force=True, ignore_permissions=True)

	for row in rates or []:
		frappe.get_doc(
			{
				"doctype": "Catalog Rate",
				"priced_doctype": priced_doctype,
				"priced_for": priced_for,
				"cluster": (row.get("cluster") or "").strip() or None,
				"currency": row["currency"],
				"rate": row["rate"],
			}
		).insert(ignore_permissions=True)


def set_catalog_rate(
	priced_doctype: str, priced_for: str, currency: str, rate, cluster: str | None = None
) -> tuple[str, bool]:
	"""Upsert one `Catalog Rate` for `(priced_for, cluster, currency)`.

	Unlike `set_catalog_rates` (which replaces *every* row for a plan), this
	touches a single cluster's row — so pricing one cluster never disturbs another.
	Returns `(name, created)`; an existing row has its `rate` updated in place.
	"""
	cluster = (cluster or "").strip() or None
	existing = frappe.db.get_value(
		"Catalog Rate",
		{
			"priced_doctype": priced_doctype,
			"priced_for": priced_for,
			"currency": currency,
			"cluster": cluster,
		},
		"name",
	)
	if existing:
		frappe.db.set_value("Catalog Rate", existing, "rate", rate)
		return existing, False

	doc = frappe.get_doc(
		{
			"doctype": "Catalog Rate",
			"priced_doctype": priced_doctype,
			"priced_for": priced_for,
			"cluster": cluster,
			"currency": currency,
			"rate": rate,
		}
	).insert(ignore_permissions=True)
	return doc.name, True


def resolve_rate(rate_rows, currency: str, cluster: str | None = None):
	"""Return the rate for (currency, cluster), or None if not configured.

	rate_rows: iterable of rows with .cluster, .currency, .rate.
	"""
	in_currency = [r for r in rate_rows if r.currency == currency]

	if cluster:
		regional = [r for r in in_currency if r.cluster == cluster]
		if regional:
			return regional[0].rate

	for r in in_currency:
		if not r.cluster:
			return r.rate

	return None


def resolve_component_rate(resource_type: str, currency: str, cluster: str | None = None):
	"""The per-unit rate card rate for one `Resource Type` (ADR 0009).

	Resolved regional-over-global exactly like a plan rate. Returns None when the
	currency has no component rate — a missing rate is *not* zero, so a config that
	can't be fully priced is refused rather than billed at nothing.
	"""
	return resolve_rate(get_catalog_rates("Resource Type", resource_type), currency, cluster)


def resolve_config_rate(includes, currency: str, cluster: str | None = None):
	"""The whole-config rate for a composition: `Σ(quantity × component_rate)`.

	`includes`: iterable of rows/dicts with `resource_type` and `quantity`. Returns
	None if *any* component has no rate for the currency — a config priced from its
	parts is only sellable when every part is priced (ADR 0009).
	"""
	total = 0.0
	for row in includes:
		resource_type = row["resource_type"] if isinstance(row, dict) else row.resource_type
		quantity = row["quantity"] if isinstance(row, dict) else row.quantity
		rate = resolve_component_rate(resource_type, currency, cluster)
		if rate is None:
			return None
		total += frappe.utils.flt(quantity) * frappe.utils.flt(rate)
	return total
