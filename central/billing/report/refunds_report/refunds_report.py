# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Refunds — money returned to a customer, to source or to wallet.

Lists each Refund with its invoice/attempt, destination and status, and headlines
the completed refund value plus the in-flight (Initiated) and Failed counts so a
stuck refund is visible. Destination = Source (back to card/bank) or Wallet
(credited to the prepaid balance).
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows = get_data(filters)
	summary = get_summary(rows)
	return columns, rows, None, None, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Refund"), "fieldname": "refund", "fieldtype": "Link", "options": "Refund", "width": 180},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 130},
		{"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Invoice", "width": 150},
		{"label": _("Payment Attempt"), "fieldname": "payment_attempt", "fieldtype": "Link", "options": "Payment Attempt", "width": 160},
		{"label": _("Destination"), "fieldname": "destination", "fieldtype": "Data", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Created"), "fieldname": "created_at", "fieldtype": "Datetime", "width": 160},
		{"label": _("Completed"), "fieldname": "completed_at", "fieldtype": "Datetime", "width": 160},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 220},
	]


def get_data(filters: dict) -> list[dict]:
	conditions = {}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("status"):
		conditions["status"] = filters["status"]
	if filters.get("destination"):
		conditions["destination"] = filters["destination"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["created_at"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["created_at"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["created_at"] = ["<=", filters["to_date"]]

	return frappe.get_all(
		"Refund",
		filters=conditions,
		fields=["name as refund", "team", "invoice", "payment_attempt", "destination",
				"status", "currency", "amount", "created_at", "completed_at", "reason"],
		order_by="created_at desc, creation desc",
	)


def get_summary(rows: list[dict]) -> list[dict]:
	initiated = sum(1 for r in rows if r.status == "Initiated")
	failed = sum(1 for r in rows if r.status == "Failed")
	# Completed refund value grouped by currency (INR and USD don't sum together).
	completed_by_currency: dict[str, float] = {}
	for r in rows:
		if r.status == "Completed":
			completed_by_currency[r.currency or "INR"] = \
				completed_by_currency.get(r.currency or "INR", 0.0) + flt(r.amount)

	summary = [
		{"label": _("Refunds"), "value": len(rows), "datatype": "Int"},
		{"label": _("In Flight"), "value": initiated, "datatype": "Int", "indicator": "orange"},
		{"label": _("Failed"), "value": failed, "datatype": "Int", "indicator": "red"},
	]
	for currency in sorted(completed_by_currency):
		summary.append({"label": _("Completed ({0})").format(currency),
						"value": flt(completed_by_currency[currency], 2), "datatype": "Float",
						"indicator": "green"})
	return summary
