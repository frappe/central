# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Teams we lost to non-payment, rather than to choice.

Read off the billing event stream: a subscription suspended for non-payment is
involuntary churn, and one that came back to Current was saved. Only transitions
recorded on the stream are visible here.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	rows = _by_month(_standing_events(filters))
	return _columns(), rows, _message(rows), _chart(rows), _summary(rows)


def _standing_events(filters: dict) -> list[dict]:
	conditions = [
		["subject_doctype", "=", "Subscription"],
		["to_state", "in", ["Past Due", "Suspended", "Current"]],
	]
	if filters.get("from_date"):
		conditions.append(["occurred_at", ">=", filters["from_date"]])
	if filters.get("to_date"):
		conditions.append(["occurred_at", "<=", frappe.utils.add_days(filters["to_date"], 1)])
	return frappe.get_all(
		"Billing Event",
		filters=conditions,
		fields=["subject", "from_state", "to_state", "occurred_at"],
		order_by="occurred_at asc",
		limit_page_length=0,
	)


def _by_month(events: list[dict]) -> list[dict]:
	buckets: dict[str, dict] = {}
	for e in events:
		month = frappe.utils.getdate(e.occurred_at).strftime("%Y-%m")
		b = buckets.setdefault(month, {"month": month, "fell_behind": 0, "suspended": 0, "recovered": 0})
		if e.to_state == "Past Due":
			b["fell_behind"] += 1
		elif e.to_state == "Suspended":
			b["suspended"] += 1
		elif e.from_state in ("Past Due", "Suspended"):
			# Back to Current from a delinquent state — a save, not a new subscription.
			b["recovered"] += 1

	rows = []
	for month in sorted(buckets, reverse=True):
		b = buckets[month]
		b["churn_rate"] = flt(b["suspended"] / b["fell_behind"] * 100, 2) if b["fell_behind"] else 0.0
		rows.append(b)
	return rows


def _columns() -> list[dict]:
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 110},
		{"label": _("Fell Behind"), "fieldname": "fell_behind", "fieldtype": "Int", "width": 120},
		{"label": _("Recovered"), "fieldname": "recovered", "fieldtype": "Int", "width": 110},
		{"label": _("Suspended"), "fieldname": "suspended", "fieldtype": "Int", "width": 110},
		{
			"label": _("Lost After Falling Behind"),
			"fieldname": "churn_rate",
			"fieldtype": "Percent",
			"width": 200,
		},
	]


def _message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No subscription changed standing in this window.")
	return _("Involuntary churn is a team we suspended for non-payment — they did not choose to leave.")


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	ordered = list(reversed(rows))
	return {
		"data": {
			"labels": [r["month"] for r in ordered],
			"datasets": [
				{"name": _("Suspended"), "values": [r["suspended"] for r in ordered]},
				{"name": _("Recovered"), "values": [r["recovered"] for r in ordered]},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	behind = sum(r["fell_behind"] for r in rows)
	suspended = sum(r["suspended"] for r in rows)
	rate = flt(suspended / behind * 100, 2) if behind else 0.0
	return [
		{"label": _("Fell Behind"), "value": behind, "datatype": "Int"},
		{
			"label": _("Recovered"),
			"value": sum(r["recovered"] for r in rows),
			"datatype": "Int",
			"indicator": "green",
		},
		{
			"label": _("Suspended"),
			"value": suspended,
			"datatype": "Int",
			"indicator": "red" if rate > 30 else "orange" if rate > 10 else "green",
		},
	]
