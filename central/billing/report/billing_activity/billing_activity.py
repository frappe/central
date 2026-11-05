# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Every billing step in one place: profiles, subscriptions, customer sync, invoices and payments."""

import frappe
from frappe import _

ROW_LIMIT = 2000


def execute(filters: dict | None = None) -> tuple:
	filters = filters or {}
	rows = frappe.get_all(
		"Billing Event",
		filters=_conditions(filters),
		fields=[
			"occurred_at",
			"team",
			"category",
			"event_type",
			"outcome",
			"reason",
			"subject_doctype",
			"subject",
			"amount",
			"currency",
			"actor",
		],
		order_by="occurred_at desc",
		limit=ROW_LIMIT,
	)
	return _columns(), rows, None, None, _summary(rows)


def _conditions(filters: dict) -> list:
	conditions = []
	for field in ("team", "category", "outcome"):
		if filters.get(field):
			conditions.append([field, "=", filters[field]])
	if filters.get("from_date"):
		conditions.append(["occurred_at", ">=", filters["from_date"]])
	if filters.get("to_date"):
		conditions.append(["occurred_at", "<", frappe.utils.add_days(filters["to_date"], 1)])
	return conditions


def _summary(rows: list) -> list[dict]:
	failed = sum(1 for row in rows if row.outcome == "Failed")
	return [
		{"label": _("Events"), "value": len(rows), "datatype": "Int", "indicator": "Blue"},
		{"label": _("Failed"), "value": failed, "datatype": "Int", "indicator": "Red" if failed else "Green"},
	]


def _columns() -> list[dict]:
	return [
		{"fieldname": "occurred_at", "label": _("When"), "fieldtype": "Datetime", "width": 170},
		{"fieldname": "team", "label": _("Team"), "fieldtype": "Link", "options": "Team", "width": 120},
		{"fieldname": "category", "label": _("Flow"), "fieldtype": "Data", "width": 130},
		{"fieldname": "event_type", "label": _("Event"), "fieldtype": "Data", "width": 220},
		{"fieldname": "outcome", "label": _("Outcome"), "fieldtype": "Data", "width": 90},
		{"fieldname": "reason", "label": _("Why"), "fieldtype": "Data", "width": 320},
		{
			"fieldname": "subject_doctype",
			"label": _("Record Type"),
			"fieldtype": "Link",
			"options": "DocType",
			"width": 130,
		},
		{
			"fieldname": "subject",
			"label": _("Record"),
			"fieldtype": "Dynamic Link",
			"options": "subject_doctype",
			"width": 150,
		},
		{
			"fieldname": "amount",
			"label": _("Amount"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 110,
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{"fieldname": "actor", "label": _("By"), "fieldtype": "Data", "width": 150},
	]
