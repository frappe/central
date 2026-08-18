# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared source for the revenue reports (MRR/YTD, cluster-wise, services).

All three read the same grain: an **Invoice Line Item** joined to its parent
invoice's currency and period, limited to real revenue (Billable invoices that
were not Cancelled). The line `amount` is the pre-tax charge — tax is a
pass-through, not revenue — so summing line amounts is additive across every cut
(by cluster, by service, by month) and each cut reconciles to the same total.

A line is **recurring** when its `resource_type` is `bundle` (the flat-rate
compute charge the invoicing engine stamps); everything else — metered overage,
consumer services, add-ons — is usage.
"""

import frappe
from frappe.utils import flt


def billable_line_items(filters: dict | None = None) -> list[dict]:
	"""Enriched line-item rows for revenue reporting, honouring team / currency /
	period-start filters. Empty when nothing qualifies."""
	filters = filters or {}
	conditions = {"invoice_type": "Billable", "status": ["!=", "Cancelled"]}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]

	from_date, to_date = filters.get("from_date"), filters.get("to_date")
	if from_date and to_date:
		conditions["period_start"] = ["between", [from_date, to_date]]
	elif from_date:
		conditions["period_start"] = [">=", from_date]
	elif to_date:
		conditions["period_start"] = ["<=", to_date]

	invoices = frappe.get_all("Invoice", filters=conditions, fields=["name", "currency", "period_start"])
	if not invoices:
		return []
	invoice_by_name = {i.name: i for i in invoices}

	items = frappe.get_all(
		"Invoice Line Item",
		filters={"parent": ["in", list(invoice_by_name)], "parenttype": "Invoice"},
		fields=["parent", "cluster", "plan", "resource_type", "amount"],
	)

	rows = []
	for it in items:
		inv = invoice_by_name.get(it.parent)
		if not inv:
			continue
		rows.append(
			{
				"invoice": it.parent,
				"currency": inv.currency or "INR",
				"period_start": inv.period_start,
				"cluster": it.cluster or "",
				"plan": it.plan or "",
				"resource_type": it.resource_type or "",
				"amount": flt(it.amount),
				"recurring": it.resource_type == "bundle",
			}
		)
	return rows
