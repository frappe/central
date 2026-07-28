# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Invoice register — every invoice with its status and money columns, plus a
status summary (counts + totals) surfaced as number cards.

Answers "how many paid / draft / open / overdue invoices this month, and for how
much." Rows are the detail; the report-summary cards carry the headline numbers.
Cost Report invoices (internal, non-billable) are excluded by default via the
Invoice Type filter so the register reflects real billing.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from central.billing.report._currency import split_currency_columns

STATUS_ORDER = ["Draft", "Open", "Paid", "Overdue", "Waived", "Cancelled"]


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows = get_data(filters)
	summary = get_summary(rows)
	chart = get_chart(rows)
	columns = split_currency_columns(
		columns, rows, ["total", "credit_applied", "expected_collection", "amount_paid"]
	)
	return columns, rows, None, chart, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Invoice", "width": 160},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 140},
		{"label": _("Type"), "fieldname": "invoice_type", "fieldtype": "Data", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Period Start"), "fieldname": "period_start", "fieldtype": "Date", "width": 100},
		{"label": _("Period End"), "fieldname": "period_end", "fieldtype": "Date", "width": 100},
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Credit Applied"), "fieldname": "credit_applied", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Expected Collection"), "fieldname": "expected_collection", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Amount Paid"), "fieldname": "amount_paid", "fieldtype": "Currency", "options": "currency", "width": 120},
	]


def get_data(filters: dict) -> list[dict]:
	conditions = {}
	# Default to real (billable) invoices; a blank filter means "all types".
	invoice_type = filters.get("invoice_type", "Billable")
	if invoice_type:
		conditions["invoice_type"] = invoice_type
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]
	if filters.get("status"):
		conditions["status"] = filters["status"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["period_start"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["period_start"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["period_start"] = ["<=", filters["to_date"]]

	return frappe.get_all(
		"Invoice",
		filters=conditions,
		fields=[
			"name as invoice", "team", "invoice_type", "status",
			"period_start", "period_end", "due_date", "currency",
			"total", "credit_applied", "expected_collection", "amount_paid",
		],
		order_by="period_start desc, creation desc",
	)


def get_summary(rows: list[dict]) -> list[dict]:
	counts = {s: 0 for s in STATUS_ORDER}
	# Money is grouped by currency — invoices span INR and USD, and a summed total
	# across the two would be meaningless.
	by_currency: dict[str, dict] = {}
	for r in rows:
		counts[r.status] = counts.get(r.status, 0) + 1
		g = by_currency.setdefault(r.currency or "INR", {"invoiced": 0.0, "outstanding": 0.0})
		g["invoiced"] += flt(r.total)
		if r.status in ("Open", "Overdue"):
			g["outstanding"] += flt(r.expected_collection)

	summary = [
		{"label": _("Invoices"), "value": len(rows), "datatype": "Int"},
		{"label": _("Paid"), "value": counts.get("Paid", 0), "datatype": "Int", "indicator": "green"},
		{"label": _("Open + Overdue"), "value": counts.get("Open", 0) + counts.get("Overdue", 0),
		 "datatype": "Int", "indicator": "orange"},
		{"label": _("Draft"), "value": counts.get("Draft", 0), "datatype": "Int", "indicator": "grey"},
	]
	for currency in sorted(by_currency):
		g = by_currency[currency]
		summary.append({"label": _("Invoiced ({0})").format(currency),
						"value": flt(g["invoiced"], 2), "datatype": "Float"})
		summary.append({"label": _("Outstanding ({0})").format(currency),
						"value": flt(g["outstanding"], 2), "datatype": "Float", "indicator": "red"})
	return summary


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	by_status = {s: 0.0 for s in STATUS_ORDER}
	for r in rows:
		by_status[r.status] = by_status.get(r.status, 0.0) + flt(r.total)
	labels = [s for s in STATUS_ORDER if by_status.get(s)]
	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Total"), "values": [flt(by_status[s], 2) for s in labels]}],
		},
		"type": "bar",
	}
