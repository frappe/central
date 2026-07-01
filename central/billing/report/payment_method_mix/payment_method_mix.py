# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment method mix & mandate coverage.

One row per method type (Card / UPI Autopay / Prepaid Credits) with a status
breakdown, so you can read how many methods are Active vs Paused/Expired/Failed and
how many need re-auth. The summary cards headline mandate coverage — the share of
teams (with any payment method) that hold an Active recurring mandate — the key
signal for whether off-session collection will work.
"""

import frappe
from frappe import _

STATUS_FIELDS = [
	("active", "Active"), ("paused", "Paused"), ("pending", "Pending Validation"),
	("expired", "Expired"), ("cancelled", "Cancelled"), ("failed", "Failed"),
]
MANDATE_TYPES = {"UPI Autopay", "Card"}  # method types that can carry a recurring mandate


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows, summary, chart = get_data(filters)
	return columns, rows, None, chart, summary


def get_columns() -> list[dict]:
	cols = [
		{"label": _("Method Type"), "fieldname": "method_type", "fieldtype": "Data", "width": 150},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90},
	]
	for fieldname, label in STATUS_FIELDS:
		cols.append({"label": _(label), "fieldname": fieldname, "fieldtype": "Int", "width": 110})
	cols.append({"label": _("Default"), "fieldname": "is_default", "fieldtype": "Int", "width": 90})
	cols.append({"label": _("Re-auth Needed"), "fieldname": "reauth_required", "fieldtype": "Int", "width": 120})
	return cols


def get_data(filters: dict):
	conditions = {}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("gateway"):
		conditions["gateway"] = filters["gateway"]

	methods = frappe.get_all(
		"Payment Method",
		filters=conditions,
		fields=["team", "method_type", "status", "is_default", "reauth_required"],
	)

	status_to_field = {label: fieldname for fieldname, label in STATUS_FIELDS}
	agg: dict[str, dict] = {}
	teams_with_method = set()
	teams_with_mandate = set()
	for m in methods:
		mt = m.method_type or _("(unset)")
		g = agg.setdefault(mt, {fieldname: 0 for fieldname, _l in STATUS_FIELDS})
		g["total"] = g.get("total", 0) + 1
		field = status_to_field.get(m.status)
		if field:
			g[field] += 1
		if m.is_default:
			g["is_default"] = g.get("is_default", 0) + 1
		if m.reauth_required:
			g["reauth_required"] = g.get("reauth_required", 0) + 1
		teams_with_method.add(m.team)
		if m.status == "Active" and m.method_type in MANDATE_TYPES:
			teams_with_mandate.add(m.team)

	rows = []
	for mt, g in sorted(agg.items()):
		rows.append({"method_type": mt, "total": g.get("total", 0),
					 "is_default": g.get("is_default", 0), "reauth_required": g.get("reauth_required", 0),
					 **{fieldname: g[fieldname] for fieldname, _l in STATUS_FIELDS}})
	rows.sort(key=lambda r: r["total"], reverse=True)

	coverage = (len(teams_with_mandate) / len(teams_with_method) * 100) if teams_with_method else 0.0
	summary = [
		{"label": _("Payment Methods"), "value": len(methods), "datatype": "Int"},
		{"label": _("Teams w/ Method"), "value": len(teams_with_method), "datatype": "Int"},
		{"label": _("Teams w/ Active Mandate"), "value": len(teams_with_mandate), "datatype": "Int", "indicator": "green"},
		{"label": _("Mandate Coverage"), "value": round(coverage, 2), "datatype": "Percent",
		 "indicator": "green" if coverage >= 70 else "orange" if coverage >= 40 else "red"},
	]
	chart = None
	if rows:
		chart = {
			"data": {"labels": [r["method_type"] for r in rows],
					 "datasets": [{"name": _("Total"), "values": [r["total"] for r in rows]}]},
			"type": "pie",
		}
	return rows, summary, chart
