# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Metered usage value vs what was invoiced FOR THAT USAGE, per team per month.

This reconciles the metered rail only — it deliberately excludes fixed plan/bundle
fees on both sides so the two columns are directly comparable (coverage ≈ 100% when
billing is correct):

  Usage value = Σ max(0, quantity − allowance) × locked_rate over Usage Rollup rows —
                the billable OVERAGE Central metered (usage within the allowance is
                free, so it is not counted).
  Invoiced    = Σ(amount) of the METERED invoice line items (resource_type ≠ "bundle")
                on the month's billable invoices — the fixed VM/bundle lines are left out.

A non-zero variance flags a billing leak (metered but not invoiced) or the reverse.
Totals are grouped BY CURRENCY — a team bills in one currency, and summing INR and
USD would be meaningless.
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

	# Usage side: billable overage worth (usage within the allowance is free).
	for r in frappe.get_all(
		"Usage Rollup", filters=usage_conditions,
		fields=["team", "period_start", "quantity", "locked_allowance", "locked_rate", "currency"],
	):
		key = (_month(r.period_start), r.team)
		g = agg.setdefault(key, {"usage_value": 0.0, "invoiced": 0.0, "currency": r.currency})
		overage = max(0.0, flt(r.quantity) - flt(r.locked_allowance))
		g["usage_value"] += overage * flt(r.locked_rate)
		g["currency"] = g["currency"] or r.currency

	# Invoiced side: only the METERED line items on the month's billable invoices.
	invoices = frappe.get_all(
		"Invoice", filters=invoice_conditions,
		fields=["name", "team", "period_start", "currency"],
	)
	inv_key = {inv.name: (_month(inv.period_start), inv.team, inv.currency) for inv in invoices}
	if inv_key:
		for li in frappe.get_all(
			"Invoice Line Item",
			filters={"parent": ["in", list(inv_key)], "resource_type": ["!=", "bundle"]},
			fields=["parent", "amount"],
		):
			month, tm, cur = inv_key[li.parent]
			g = agg.setdefault((month, tm), {"usage_value": 0.0, "invoiced": 0.0, "currency": cur})
			g["invoiced"] += flt(li.amount)
			g["currency"] = g["currency"] or cur

	rows = []
	# Per-currency totals — never sum across currencies.
	totals: dict[str, dict] = {}
	for (month, tm), g in agg.items():
		usage_value = flt(g["usage_value"], 2)
		invoiced = flt(g["invoiced"], 2)
		currency = g["currency"] or "INR"
		# A team with no metered footprint this month contributes no reconciliation row.
		if usage_value == 0 and invoiced == 0:
			continue
		coverage = (invoiced / usage_value * 100) if usage_value else 0.0
		rows.append({
			"month": month, "team": tm, "currency": currency,
			"usage_value": usage_value, "invoiced": invoiced,
			"variance": flt(invoiced - usage_value, 2), "coverage_pct": flt(coverage, 2),
		})
		t = totals.setdefault(currency, {"usage": 0.0, "invoiced": 0.0})
		t["usage"] += usage_value
		t["invoiced"] += invoiced
	rows.sort(key=lambda r: (r["month"], r["team"]), reverse=True)

	summary = []
	for currency in sorted(totals):
		t = totals[currency]
		summary.append({"label": _("Usage Value ({0})").format(currency),
						"value": flt(t["usage"], 2), "datatype": "Float"})
		summary.append({"label": _("Invoiced ({0})").format(currency),
						"value": flt(t["invoiced"], 2), "datatype": "Float"})
		summary.append({"label": _("Variance ({0})").format(currency),
						"value": flt(t["invoiced"] - t["usage"], 2), "datatype": "Float",
						"indicator": "green" if abs(t["invoiced"] - t["usage"]) < 0.01 else "red"})
	return rows, summary
