# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Credit wallet movements — the append-only Credit Ledger Entry feed.

Every credit (top-up, refund-to-wallet, promo) and debit (invoice settlement)
against a team's prepaid wallet, with the running balance carried on each entry.
The summary cards headline credited vs debited vs net over the filtered window.
"""

import frappe
from frappe import _
from frappe.utils import flt
from central.billing.report._currency import split_currency_columns


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows = get_data(filters)
	summary = get_summary(rows)
	columns = split_currency_columns(columns, rows, ["amount", "running_balance"])
	return columns, rows, None, None, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Entry"), "fieldname": "entry", "fieldtype": "Link", "options": "Credit Ledger Entry", "width": 200},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 130},
		{"label": _("Date"), "fieldname": "created_at", "fieldtype": "Datetime", "width": 160},
		{"label": _("Type"), "fieldname": "entry_type", "fieldtype": "Data", "width": 80},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Running Balance"), "fieldname": "running_balance", "fieldtype": "Currency", "options": "currency", "width": 140},
		{"label": _("Reference"), "fieldname": "reference", "fieldtype": "Data", "width": 200},
		{"label": _("Note"), "fieldname": "note", "fieldtype": "Data", "width": 220},
	]


def get_data(filters: dict) -> list[dict]:
	conditions = {}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("entry_type"):
		conditions["entry_type"] = filters["entry_type"]
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]
	if filters.get("from_date") and filters.get("to_date"):
		conditions["created_at"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["created_at"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["created_at"] = ["<=", filters["to_date"]]

	entries = frappe.get_all(
		"Credit Ledger Entry",
		filters=conditions,
		fields=["name as entry", "team", "created_at", "entry_type", "currency", "amount",
				"running_balance", "reference_type", "reference_name", "note"],
		order_by="created_at desc, creation desc",
	)
	for e in entries:
		ref = " ".join(p for p in [e.reference_type, e.reference_name] if p)
		e["reference"] = ref or None
	return entries


def get_summary(rows: list[dict]) -> list[dict]:
	# Group money by currency — a team's wallet is in one currency, and summing INR
	# and USD movements together would be meaningless.
	by_currency: dict[str, dict] = {}
	for r in rows:
		g = by_currency.setdefault(r.currency or "INR", {"credited": 0.0, "debited": 0.0})
		if r.entry_type == "Credit":
			g["credited"] += flt(r.amount)
		elif r.entry_type == "Debit":
			g["debited"] += flt(r.amount)

	summary = [{"label": _("Movements"), "value": len(rows), "datatype": "Int"}]
	for currency in sorted(by_currency):
		g = by_currency[currency]
		net = g["credited"] - g["debited"]
		summary.append({"label": _("Credited ({0})").format(currency),
						"value": flt(g["credited"], 2), "datatype": "Float", "indicator": "green"})
		summary.append({"label": _("Net ({0})").format(currency), "value": flt(net, 2),
						"datatype": "Float", "indicator": "green" if net >= 0 else "red"})
	return summary
