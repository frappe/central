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

from central.billing.report._currency import split_currency_columns


def execute(filters: dict | None = None):
	filters = filters or {}
	if filters.get("group_by") == "Failure Code":
		return execute_failure_breakdown(filters)
	if filters.get("group_by") == "Month":
		return execute_by_month(filters)
	if filters.get("group_by") == "Rail":
		return execute_by_rail(filters)
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
	attempts = frappe.get_all(
		"Payment Attempt",
		filters=conditions,
		fields=[
			"gateway",
			"status",
			"amount",
			"currency",
			"failure_code",
			"failure_reason",
			"initiated_at",
			"payment_method",
		],
	)
	networks = _networks([a.payment_method for a in attempts if a.payment_method])
	for a in attempts:
		a.network = networks.get(a.payment_method) or _("(unknown)")
	return attempts


def _networks(method_names: list[str]) -> dict:
	"""Card network per method, read in one go rather than per attempt."""
	if not method_names:
		return {}
	rows = frappe.get_all(
		"Payment Method",
		filters={"name": ["in", list(set(method_names))]},
		fields=["name", "card_network"],
	)
	return {r.name: r.card_network for r in rows}


# ── Auth rate over time ──────────────────────────────────────────────────────


def execute_by_month(filters: dict):
	"""The same success rate, per gateway per month — a dip is only legible against a trend."""
	columns = [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 110},
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 180,
		},
		{"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int", "width": 100},
		{"label": _("Captured"), "fieldname": "captured", "fieldtype": "Int", "width": 100},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 90},
		{"label": _("Success Rate"), "fieldname": "success_rate", "fieldtype": "Percent", "width": 120},
	]

	agg: dict[tuple, dict] = {}
	for a in _attempts(filters):
		if not a.initiated_at:
			continue
		key = (frappe.utils.getdate(a.initiated_at).strftime("%Y-%m"), a.gateway or _("(none)"))
		g = agg.setdefault(key, {"attempts": 0, "captured": 0, "failed": 0})
		g["attempts"] += 1
		if a.status == "Captured":
			g["captured"] += 1
		elif a.status == "Failed":
			g["failed"] += 1

	rows = [
		{
			"month": month,
			"gateway": gateway,
			**g,
			"success_rate": flt(g["captured"] / g["attempts"] * 100, 2) if g["attempts"] else 0.0,
		}
		for (month, gateway), g in sorted(agg.items(), reverse=True)
	]

	chart = None
	if rows:
		months = sorted({r["month"] for r in rows})
		by_gateway: dict[str, dict] = {}
		for r in rows:
			by_gateway.setdefault(r["gateway"], {})[r["month"]] = r["success_rate"]
		chart = {
			"data": {
				"labels": months,
				"datasets": [
					{"name": gateway, "values": [series.get(m, 0.0) for m in months]}
					for gateway, series in sorted(by_gateway.items())
				],
			},
			"type": "line",
		}
	return columns, rows, None, chart, None


# ── Gateway x network x currency ─────────────────────────────────────────────


def execute_by_rail(filters: dict):
	"""Success rate split the way the routing decision needs to be judged (ADR 0022).

	A gateway-level number hides the thing worth knowing: whether a network does
	worse on one rail than the other. Domestic acquirers often beat cross-border ones
	on authorisation, and this is the report that says whether ours does.
	"""
	columns = [
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 160,
		},
		{"label": _("Network"), "fieldname": "network", "fieldtype": "Data", "width": 140},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 100,
		},
		{"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int", "width": 100},
		{"label": _("Captured"), "fieldname": "captured", "fieldtype": "Int", "width": 100},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 90},
		{"label": _("Success Rate"), "fieldname": "success_rate", "fieldtype": "Percent", "width": 120},
	]

	agg: dict[tuple, dict] = {}
	for a in _attempts(filters):
		key = (a.gateway or _("(none)"), a.network, a.currency or _("(none)"))
		g = agg.setdefault(key, {"attempts": 0, "captured": 0, "failed": 0})
		g["attempts"] += 1
		if a.status == "Captured":
			g["captured"] += 1
		elif a.status == "Failed":
			g["failed"] += 1

	rows = [
		{
			"gateway": gateway,
			"network": network,
			"currency": currency,
			**g,
			"success_rate": flt(g["captured"] / g["attempts"] * 100, 2) if g["attempts"] else 0.0,
		}
		for (gateway, network, currency), g in agg.items()
	]
	rows.sort(key=lambda r: r["attempts"], reverse=True)
	return columns, rows, None, None, None


# ── Per-gateway ratio ────────────────────────────────────────────────────────


def execute_by_gateway(filters: dict):
	columns = [
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 180,
		},
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
		g = agg.setdefault(
			gw,
			{
				"attempts": 0,
				"captured": 0,
				"authorised": 0,
				"failed": 0,
				"refunded": 0,
				"captured_amount": 0.0,
				"currency": a.currency,
			},
		)
		g["currency"] = g["currency"] or a.currency  # a gateway is single-currency
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
		rows.append(
			{
				"gateway": gw,
				**g,
				"success_rate": flt(rate, 2),
				"captured_amount": flt(g["captured_amount"], 2),
			}
		)
		tot_attempts += g["attempts"]
		tot_captured += g["captured"]
	rows.sort(key=lambda r: r["attempts"], reverse=True)

	overall = (tot_captured / tot_attempts * 100) if tot_attempts else 0.0
	summary = [
		{"label": _("Total Attempts"), "value": tot_attempts, "datatype": "Int"},
		{"label": _("Captured"), "value": tot_captured, "datatype": "Int", "indicator": "green"},
		{
			"label": _("Overall Success Rate"),
			"value": flt(overall, 2),
			"datatype": "Percent",
			"indicator": "green" if overall >= 80 else "orange" if overall >= 50 else "red",
		},
	]
	chart = None
	if rows:
		chart = {
			"data": {
				"labels": [r["gateway"] for r in rows],
				"datasets": [{"name": _("Success Rate"), "values": [r["success_rate"] for r in rows]}],
			},
			"type": "bar",
		}
	columns = split_currency_columns(columns, rows, ["captured_amount"])
	return columns, rows, None, chart, summary


# ── Failure-code breakdown ───────────────────────────────────────────────────


def execute_failure_breakdown(filters: dict):
	columns = [
		{
			"label": _("Gateway"),
			"fieldname": "gateway",
			"fieldtype": "Link",
			"options": "Payment Gateway",
			"width": 180,
		},
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
	summary = [
		{
			"label": _("Failed Attempts"),
			"value": sum(r["count"] for r in rows),
			"datatype": "Int",
			"indicator": "red",
		}
	]
	return columns, rows, None, None, summary
