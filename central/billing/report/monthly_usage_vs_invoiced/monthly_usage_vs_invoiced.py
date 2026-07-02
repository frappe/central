# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Metered usage value vs what was invoiced, per team per month.

Usage value = Σ(quantity × locked_rate) over Usage Rollup rows in the month — the
metered run-rate Central recorded. Invoiced = Σ(Invoice.total) for billable
invoices whose period falls in the month. The variance flags billing leakage
(usage recorded but not billed) or the reverse.

Caveat: an invoice total also carries fixed plan/bundle fees, not only metered
overage, so the two columns are a reconciliation aid — a large *negative* variance
(usage far above invoiced) is the signal to chase, not an exact equality check.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows, summary = get_data(filters)
	return columns, rows, None, None, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 100},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 160},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{"label": _("Usage Value"), "fieldname": "usage_value", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Invoiced"), "fieldname": "invoiced", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Coverage %"), "fieldname": "coverage_pct", "fieldtype": "Percent", "width": 110},
	]


def _month(d) -> str:
	"""YYYY-MM key from a date/datetime."""
	return str(d)[:7]


def get_data(filters: dict):
	team = filters.get("team")
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")

	usage_conditions = {}
	invoice_conditions = {"invoice_type": "Billable"}
	if team:
		usage_conditions["team"] = team
		invoice_conditions["team"] = team
	if from_date and to_date:
		usage_conditions["period_start"] = ["between", [from_date, to_date]]
		invoice_conditions["period_start"] = ["between", [from_date, to_date]]
	elif from_date:
		usage_conditions["period_start"] = [">=", from_date]
		invoice_conditions["period_start"] = [">=", from_date]
	elif to_date:
		usage_conditions["period_start"] = ["<=", to_date]
		invoice_conditions["period_start"] = ["<=", to_date]

	# (month, team) -> aggregate. Currency comes from whichever source has it; a team
	# bills in one currency so the two agree.
	agg: dict[tuple, dict] = {}

	for r in frappe.get_all(
		"Usage Rollup", filters=usage_conditions,
		fields=["team", "period_start", "quantity", "locked_rate", "currency"],
	):
		key = (_month(r.period_start), r.team)
		g = agg.setdefault(key, {"usage_value": 0.0, "invoiced": 0.0, "currency": r.currency})
		g["usage_value"] += flt(r.quantity) * flt(r.locked_rate)
		g["currency"] = g["currency"] or r.currency

	for r in frappe.get_all(
		"Invoice", filters=invoice_conditions,
		fields=["team", "period_start", "total", "currency"],
	):
		key = (_month(r.period_start), r.team)
		g = agg.setdefault(key, {"usage_value": 0.0, "invoiced": 0.0, "currency": r.currency})
		g["invoiced"] += flt(r.total)
		g["currency"] = g["currency"] or r.currency

	rows = []
	tot_usage = tot_invoiced = 0.0
	for (month, tm), g in agg.items():
		usage_value = flt(g["usage_value"], 2)
		invoiced = flt(g["invoiced"], 2)
		coverage = (invoiced / usage_value * 100) if usage_value else 0.0
		rows.append({
			"month": month, "team": tm, "currency": g["currency"] or "INR",
			"usage_value": usage_value, "invoiced": invoiced,
			"variance": flt(invoiced - usage_value, 2), "coverage_pct": flt(coverage, 2),
		})
		tot_usage += usage_value
		tot_invoiced += invoiced
	rows.sort(key=lambda r: (r["month"], r["team"]), reverse=True)

	summary = [
		{"label": _("Usage Value"), "value": flt(tot_usage, 2), "datatype": "Float"},
		{"label": _("Invoiced"), "value": flt(tot_invoiced, 2), "datatype": "Float"},
		{"label": _("Variance"), "value": flt(tot_invoiced - tot_usage, 2), "datatype": "Float",
		 "indicator": "green" if tot_invoiced >= tot_usage else "red"},
	]
	return rows, summary
