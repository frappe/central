# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared source for the revenue reports (MRR/YTD, cluster-wise, services).

All three read the same grain: an **Invoice Line Item** joined to its parent
invoice's currency and period, limited to real revenue: Billable invoices of
external teams that were neither Cancelled nor Waived. The line `amount` is the
pre-tax charge — tax is a pass-through, not revenue — so summing line amounts is
additive across every cut (by cluster, by service, by month) and each cut
reconciles to the same total.

A line is **recurring** when its `resource_type` is `bundle` (the flat-rate
compute charge the invoicing engine stamps); everything else — metered overage,
consumer services, add-ons — is usage.
"""

import frappe
from frappe.utils import cint, flt

from central.billing.revenue.tax import internal_teams

# A cancelled invoice was never owed, and a waived one was given away.
NOT_REVENUE_STATUSES = ("Cancelled", "Waived")


def is_revenue(status: str, team: str, internal: set[str]) -> bool:
	"""Whether an invoice in `status` for `team` counts as revenue."""
	return status not in NOT_REVENUE_STATUSES and team not in internal


def revenue_criterion(invoice):
	"""Query condition on an Invoice table that keeps only revenue."""
	criterion = invoice.status.notin(NOT_REVENUE_STATUSES)
	internal = internal_teams()
	if internal:
		criterion &= invoice.team.notin(list(internal))
	return criterion


def billable_line_items(filters: dict | None = None) -> list[dict]:
	"""Enriched line-item rows for revenue reporting, honouring team / currency /
	period-start filters. `include_internal_and_waived` adds back the usage that is
	not revenue. Empty when nothing qualifies."""
	filters = filters or {}
	conditions = [["invoice_type", "=", "Billable"], *_revenue_conditions(filters)]
	if filters.get("team"):
		conditions.append(["team", "=", filters["team"]])
	if filters.get("currency"):
		conditions.append(["currency", "=", filters["currency"]])

	from_date, to_date = filters.get("from_date"), filters.get("to_date")
	if from_date and to_date:
		conditions.append(["period_start", "between", [from_date, to_date]])
	elif from_date:
		conditions.append(["period_start", ">=", from_date])
	elif to_date:
		conditions.append(["period_start", "<=", to_date])

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


def _revenue_conditions(filters: dict) -> list:
	if cint(filters.get("include_internal_and_waived")):
		return [["status", "!=", "Cancelled"]]
	conditions = [["status", "not in", NOT_REVENUE_STATUSES]]
	internal = internal_teams()
	if internal:
		conditions.append(["team", "not in", list(internal)])
	return conditions
