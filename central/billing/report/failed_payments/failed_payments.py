# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Failed payments — a glance view of every declined charge and why.

One row per failed Payment Attempt, newest first, with the granular decline
reason (Stripe `decline_code` / Razorpay `error_reason`) beside the top-level
code so an operator can see at a glance *why* collection is failing — not just
that it did. The chart buckets failures by reason so the dominant cause (e.g.
insufficient_funds) stands out. Pair it with Gateway Payment Success Ratio,
which gives the aggregate rate; this one names the individual failures.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	rows = _failed_attempts(filters)
	columns = _columns()
	chart = _reason_chart(rows)
	summary = _summary(rows)
	return columns, rows, None, chart, summary


def _failed_attempts(filters: dict) -> list[dict]:
	conditions = {"status": "Failed"}
	for field in ("gateway", "team", "decline_code"):
		if filters.get(field):
			conditions[field] = filters[field]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["initiated_at"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["initiated_at"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["initiated_at"] = ["<=", filters["to_date"]]
	return frappe.get_all(
		"Payment Attempt",
		filters=conditions,
		fields=[
			"name", "initiated_at", "team", "invoice", "gateway", "payment_method",
			"amount", "currency", "retry_number",
			"failure_code", "decline_code", "failure_reason",
		],
		order_by="initiated_at desc",
	)


def _columns() -> list[dict]:
	return [
		{"label": _("Attempt"), "fieldname": "name", "fieldtype": "Link", "options": "Payment Attempt", "width": 150},
		{"label": _("Failed At"), "fieldname": "initiated_at", "fieldtype": "Datetime", "width": 165},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 140},
		{"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Invoice", "width": 150},
		{"label": _("Gateway"), "fieldname": "gateway", "fieldtype": "Link", "options": "Payment Gateway", "width": 120},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Float", "width": 100},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{"label": _("Retry"), "fieldname": "retry_number", "fieldtype": "Int", "width": 70},
		{"label": _("Failure Code"), "fieldname": "failure_code", "fieldtype": "Data", "width": 150},
		{"label": _("Decline Code"), "fieldname": "decline_code", "fieldtype": "Data", "width": 160},
		{"label": _("Reason"), "fieldname": "failure_reason", "fieldtype": "Data", "width": 300},
	]


def _reason(row: dict) -> str:
	"""The most specific label available for a failure: the granular decline code,
	then the top-level code, then a catch-all."""
	return row.get("decline_code") or row.get("failure_code") or _("(unknown)")


def _reason_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	counts: dict[str, int] = {}
	for r in rows:
		counts[_reason(r)] = counts.get(_reason(r), 0) + 1
	top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
	return {
		"data": {"labels": [k for k, _c in top],
				 "datasets": [{"name": _("Failures"), "values": [c for _k, c in top]}]},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	if not rows:
		return [{"label": _("Failed Payments"), "value": 0, "datatype": "Int", "indicator": "green"}]
	amount = flt(sum(flt(r.get("amount")) for r in rows), 2)
	teams = len({r.get("team") for r in rows if r.get("team")})
	counts: dict[str, int] = {}
	for r in rows:
		counts[_reason(r)] = counts.get(_reason(r), 0) + 1
	top_reason, top_count = max(counts.items(), key=lambda kv: kv[1])
	return [
		{"label": _("Failed Payments"), "value": len(rows), "datatype": "Int", "indicator": "red"},
		{"label": _("Amount Not Collected"), "value": amount, "datatype": "Float", "indicator": "red"},
		{"label": _("Teams Affected"), "value": teams, "datatype": "Int", "indicator": "orange"},
		{"label": _("Top Reason"), "value": f"{top_reason} ({top_count})", "datatype": "Data"},
	]
