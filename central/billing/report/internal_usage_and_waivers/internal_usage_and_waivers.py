# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What internal teams used, and how much of it was waived, per invoice period."""

import frappe
from frappe import _

from central.billing.report._currency import split_currency_columns

MONEY_FIELDS = ("usage", "waived")


def execute(filters: dict | None = None):
	filters = filters or {}
	rows = _rows(filters)
	columns = split_currency_columns(_columns(), rows, MONEY_FIELDS)
	return columns, rows, _message(rows)


def _rows(filters: dict) -> list[dict]:
	invoice = frappe.qb.DocType("Invoice")
	team = frappe.qb.DocType("Team")
	query = (
		frappe.qb.from_(invoice)
		.join(team)
		.on(team.name == invoice.team)
		.select(
			invoice.team,
			team.team_name,
			invoice.period_start,
			invoice.period_end,
			invoice.name.as_("invoice"),
			invoice.currency,
			invoice.subtotal.as_("usage"),
			invoice.total.as_("waived"),
		)
		.where(invoice.status == "Waived")
		.orderby(invoice.period_start, order=frappe.qb.desc)
		.orderby(invoice.team)
	)
	if filters.get("from_date"):
		query = query.where(invoice.period_start >= filters["from_date"])
	if filters.get("to_date"):
		query = query.where(invoice.period_start <= filters["to_date"])
	if filters.get("team"):
		query = query.where(invoice.team == filters["team"])
	return query.run(as_dict=True)


def _message(rows: list[dict]) -> str:
	if not rows:
		return _("No waived invoices in this period.")
	teams = len({row["team"] for row in rows})
	return _("{0} waived invoice(s) across {1} team(s).").format(len(rows), teams)


def _columns() -> list[dict]:
	return [
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 130},
		{"label": _("Team Name"), "fieldname": "team_name", "fieldtype": "Data", "width": 180},
		{"label": _("Period Start"), "fieldname": "period_start", "fieldtype": "Date", "width": 110},
		{"label": _("Period End"), "fieldname": "period_end", "fieldtype": "Date", "width": 110},
		{
			"label": _("Invoice"),
			"fieldname": "invoice",
			"fieldtype": "Link",
			"options": "Invoice",
			"width": 130,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{
			"label": _("Usage"),
			"fieldname": "usage",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Waived"),
			"fieldname": "waived",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
	]
