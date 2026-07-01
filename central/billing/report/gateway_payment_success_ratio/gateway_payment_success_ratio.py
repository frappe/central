# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment attempt success ratio by gateway.

For each gateway: how many attempts were made and what share were captured, with
the authorised / failed / refunded counts alongside so a dip in success rate can be
read against volume. Switch Group By to "Failure Code" to see *why* attempts fail
(the failure_code / failure_reason frequency), which is the actionable follow-up to
a low success rate.

Success rate = Captured ÷ total attempts. Captured is the terminal success state
(the invoice/top-up settles on the capture webhook); Authorised is counted
separately as in-flight.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	if filters.get("group_by") == "Failure Code":
		return execute_failure_breakdown(filters)
	return execute_by_gateway(filters)


def _attempts(filters: dict) -> list[dict]:
	conditions = {}
	if filters.get("gateway"):
		conditions["gateway"] = filters["gateway"]
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["initiated_at"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["initiated_at"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["initiated_at"] = ["<=", filters["to_date"]]
	return frappe.get_all(
		"Payment Attempt",
		filters=conditions,
		fields=["gateway", "status", "amount", "currency", "failure_code", "failure_reason"],
	)


# ── Per-gateway ratio ────────────────────────────────────────────────────────

def execute_by_gateway(filters: dict):
	columns = [
		{"label": _("Gateway"), "fieldname": "gateway", "fieldtype": "Link", "options": "Payment Gateway", "width": 180},
		{"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int", "width": 100},
		{"label": _("Captured"), "fieldname": "captured", "fieldtype": "Int", "width": 100},
		{"label": _("Authorised"), "fieldname": "authorised", "fieldtype": "Int", "width": 100},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 90},
		{"label": _("Refunded"), "fieldname": "refunded", "fieldtype": "Int", "width": 90},
		{"label": _("Success Rate"), "fieldname": "success_rate", "fieldtype": "Percent", "width": 120},
		{"label": _("Captured Amount"), "fieldname": "captured_amount", "fieldtype": "Float", "width": 140},
	]

	agg: dict[str, dict] = {}
	for a in _attempts(filters):
		gw = a.gateway or _("(none)")
		g = agg.setdefault(gw, {"attempts": 0, "captured": 0, "authorised": 0,
								"failed": 0, "refunded": 0, "captured_amount": 0.0})
		g["attempts"] += 1
		if a.status == "Captured":
			g["captured"] += 1
			g["captured_amount"] += flt(a.amount)
		elif a.status == "Authorised":
			g["authorised"] += 1
		elif a.status == "Failed":
			g["failed"] += 1
		elif a.status == "Refunded":
			g["refunded"] += 1

	rows = []
	tot_attempts = tot_captured = 0
	for gw, g in sorted(agg.items()):
		rate = (g["captured"] / g["attempts"] * 100) if g["attempts"] else 0.0
		rows.append({"gateway": gw, **g, "success_rate": flt(rate, 2),
					 "captured_amount": flt(g["captured_amount"], 2)})
		tot_attempts += g["attempts"]
		tot_captured += g["captured"]
	rows.sort(key=lambda r: r["attempts"], reverse=True)

	overall = (tot_captured / tot_attempts * 100) if tot_attempts else 0.0
	summary = [
		{"label": _("Total Attempts"), "value": tot_attempts, "datatype": "Int"},
		{"label": _("Captured"), "value": tot_captured, "datatype": "Int", "indicator": "green"},
		{"label": _("Overall Success Rate"), "value": flt(overall, 2), "datatype": "Percent",
		 "indicator": "green" if overall >= 80 else "orange" if overall >= 50 else "red"},
	]
	chart = None
	if rows:
		chart = {
			"data": {"labels": [r["gateway"] for r in rows],
					 "datasets": [{"name": _("Success Rate"), "values": [r["success_rate"] for r in rows]}]},
			"type": "bar",
		}
	return columns, rows, None, chart, summary


# ── Failure-code breakdown ───────────────────────────────────────────────────

def execute_failure_breakdown(filters: dict):
	columns = [
		{"label": _("Gateway"), "fieldname": "gateway", "fieldtype": "Link", "options": "Payment Gateway", "width": 180},
		{"label": _("Failure Code"), "fieldname": "failure_code", "fieldtype": "Data", "width": 180},
		{"label": _("Failure Reason"), "fieldname": "failure_reason", "fieldtype": "Data", "width": 320},
		{"label": _("Count"), "fieldname": "count", "fieldtype": "Int", "width": 90},
	]
	agg: dict[tuple, dict] = {}
	for a in _attempts(filters):
		if a.status != "Failed":
			continue
		key = (a.gateway or _("(none)"), a.failure_code or _("(unknown)"))
		g = agg.setdefault(key, {"failure_reason": a.failure_reason, "count": 0})
		g["count"] += 1
	rows = [
		{"gateway": gw, "failure_code": code, "failure_reason": g["failure_reason"], "count": g["count"]}
		for (gw, code), g in agg.items()
	]
	rows.sort(key=lambda r: r["count"], reverse=True)
	summary = [{"label": _("Failed Attempts"), "value": sum(r["count"] for r in rows),
				"datatype": "Int", "indicator": "red"}]
	return columns, rows, None, None, summary
