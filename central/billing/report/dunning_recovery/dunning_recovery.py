# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Of the invoices that went overdue, how many did we eventually collect.

Read off the billing event stream: an invoice enters dunning when it moves to
Overdue, and is recovered if it later reaches Paid. Only transitions recorded on the
stream are visible here, so months before it existed read as empty.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	overdue, paid = _invoice_events(filters)
	rows = _by_month(overdue, paid)
	return _columns(), rows, _message(rows), _chart(rows), _summary(rows)


def _invoice_events(filters: dict) -> tuple[dict, set]:
	"""When each invoice in the window first went overdue, and which of them were paid.

	The window picks the invoices that entered dunning. Whether they were recovered is
	then asked without a date bound, because a December overdue settled in January is
	still a recovery.
	"""
	conditions = [["subject_doctype", "=", "Invoice"], ["to_state", "=", "Overdue"]]
	if filters.get("from_date"):
		conditions.append(["occurred_at", ">=", filters["from_date"]])
	if filters.get("to_date"):
		conditions.append(["occurred_at", "<", frappe.utils.add_days(filters["to_date"], 1)])

	overdue: dict[str, str] = {}
	for e in frappe.get_all(
		"Billing Event",
		filters=conditions,
		fields=["subject", "occurred_at"],
		order_by="occurred_at asc",
		limit_page_length=0,
	):
		overdue.setdefault(e.subject, e.occurred_at)

	if not overdue:
		return {}, set()
	paid = set(
		frappe.get_all(
			"Billing Event",
			filters=[
				["subject_doctype", "=", "Invoice"],
				["to_state", "=", "Paid"],
				["subject", "in", list(overdue)],
			],
			pluck="subject",
			limit_page_length=0,
		)
	)
	return overdue, paid


def _by_month(overdue: dict, paid: set) -> list[dict]:
	buckets: dict[str, dict] = {}
	for invoice, when in overdue.items():
		month = frappe.utils.getdate(when).strftime("%Y-%m")
		bucket = buckets.setdefault(month, {"month": month, "went_overdue": 0, "recovered": 0})
		bucket["went_overdue"] += 1
		if invoice in paid:
			bucket["recovered"] += 1

	rows = []
	for month in sorted(buckets, reverse=True):
		b = buckets[month]
		b["still_owed"] = b["went_overdue"] - b["recovered"]
		b["recovery_rate"] = flt(b["recovered"] / b["went_overdue"] * 100, 2) if b["went_overdue"] else 0.0
		rows.append(b)
	return rows


def _columns() -> list[dict]:
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 110},
		{"label": _("Went Overdue"), "fieldname": "went_overdue", "fieldtype": "Int", "width": 130},
		{"label": _("Recovered"), "fieldname": "recovered", "fieldtype": "Int", "width": 110},
		{"label": _("Still Owed"), "fieldname": "still_owed", "fieldtype": "Int", "width": 110},
		{"label": _("Recovery Rate"), "fieldname": "recovery_rate", "fieldtype": "Percent", "width": 130},
	]


def _message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No invoice went overdue in this window.")
	return _("An invoice counts as recovered once it reaches Paid, however long that took.")


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	ordered = list(reversed(rows))
	return {
		"data": {
			"labels": [r["month"] for r in ordered],
			"datasets": [{"name": _("Recovery rate"), "values": [r["recovery_rate"] for r in ordered]}],
		},
		"type": "line",
	}


def _summary(rows: list[dict]) -> list[dict]:
	overdue = sum(r["went_overdue"] for r in rows)
	recovered = sum(r["recovered"] for r in rows)
	rate = flt(recovered / overdue * 100, 2) if overdue else 0.0
	return [
		{"label": _("Went Overdue"), "value": overdue, "datatype": "Int"},
		{"label": _("Recovered"), "value": recovered, "datatype": "Int", "indicator": "green"},
		{
			"label": _("Recovery Rate"),
			"value": rate,
			"datatype": "Percent",
			"indicator": "green" if rate >= 70 else "orange" if rate >= 40 else "red",
		},
	]
