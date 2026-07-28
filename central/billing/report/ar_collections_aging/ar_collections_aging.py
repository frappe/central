# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Accounts-receivable aging — outstanding collection on Open/Overdue invoices,
bucketed by how far past the due date they are as of a chosen date.

`expected_collection` (total net of applied credit) is placed into the age bucket
for `as_of_date - due_date`, so the columns sum to the cash at risk in each band.
The classic collections worklist: chase the 60+/90+ columns first.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from central.billing.report._currency import split_currency_columns

BUCKETS = [
	("current", _("Current"), 0),
	("b1_30", _("1-30"), 30),
	("b31_60", _("31-60"), 60),
	("b61_90", _("61-90"), 90),
	("b90_plus", _("90+"), None),
]


def execute(filters: dict | None = None):
	filters = filters or {}
	as_of = getdate(filters.get("as_of_date") or nowdate())
	columns = get_columns()
	rows, summary = get_data(filters, as_of)
	money_fields = [fieldname for fieldname, _label, _days in BUCKETS] + ["outstanding"]
	columns = split_currency_columns(columns, rows, money_fields)
	return columns, rows, None, None, summary


def get_columns() -> list[dict]:
	cols = [
		{"label": _("Invoice"), "fieldname": "invoice", "fieldtype": "Link", "options": "Invoice", "width": 160},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 80},
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 110},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
	]
	for fieldname, label, _days in BUCKETS:
		cols.append({"label": label, "fieldname": fieldname, "fieldtype": "Currency",
					 "options": "currency", "width": 110})
	cols.append({"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency",
				 "options": "currency", "width": 130})
	return cols


def _bucket_for(days_overdue: int) -> str:
	"""Bucket fieldname for a given days-overdue (<=0 is Current)."""
	if days_overdue <= 0:
		return "current"
	for fieldname, _label, upper in BUCKETS[1:]:
		if upper is None or days_overdue <= upper:
			return fieldname
	return "b90_plus"


def get_data(filters: dict, as_of):
	conditions = {"status": ["in", ["Open", "Overdue"]], "expected_collection": [">", 0]}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]

	invoices = frappe.get_all(
		"Invoice",
		filters=conditions,
		fields=["name as invoice", "team", "status", "due_date", "currency", "expected_collection"],
		order_by="due_date asc",
	)

	rows = []
	# Outstanding is grouped by currency — INR and USD must not sum into one figure in no
	# currency at all. The per-bucket breakdown lives in the (per-currency) columns and
	# the total row; the summary carries the per-currency headline.
	outstanding_by_currency: dict[str, float] = {}
	for inv in invoices:
		outstanding = flt(inv.expected_collection)
		days_overdue = date_diff(as_of, inv.due_date) if inv.due_date else 0
		bucket = _bucket_for(days_overdue)
		row = {b[0]: 0.0 for b in BUCKETS}
		row[bucket] = outstanding
		currency = inv.currency or "INR"
		row.update({
			"invoice": inv.invoice, "team": inv.team, "status": inv.status,
			"due_date": inv.due_date, "days_overdue": max(days_overdue, 0),
			"currency": currency, "outstanding": outstanding,
		})
		rows.append(row)
		outstanding_by_currency[currency] = outstanding_by_currency.get(currency, 0.0) + outstanding

	summary = [
		{"label": _("Outstanding ({0})").format(currency), "value": flt(amount, 2),
		 "datatype": "Float", "indicator": "red"}
		for currency, amount in sorted(outstanding_by_currency.items())
	]
	return rows, summary
