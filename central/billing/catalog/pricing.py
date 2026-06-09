# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rate resolution — region x currency.

Shared by Plan (bundle) and Add-on. A rate is resolved for a team's billing
currency and the resource's cluster: the most-specific region match wins,
falling back to the global (blank-cluster) row.

Rates live in one standalone `Catalog Rate` DocType (ERPNext `Item Price` style),
linked to a Plan or Add-on via a Dynamic Link (`priced_doctype` + `priced_for`).
"""

import frappe


def get_catalog_rates(priced_doctype: str, priced_for: str) -> list:
	"""All `Catalog Rate` rows (cluster/currency/rate) for one plan or add-on."""
	return frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": priced_doctype, "priced_for": priced_for},
		fields=["cluster", "currency", "rate"],
	)


def set_catalog_rates(priced_doctype: str, priced_for: str, rates) -> None:
	"""Replace every `Catalog Rate` for a plan/add-on with the given rows.

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
