# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Which teams are about to be cut off, and on what date.

Unlike the revenue projection, this one computes in the request — and can, because it
costs nothing. There is no rating here: it is the dunning ladder applied to invoices
that already exist, so it scales with how many customers are behind rather than with how
many customers there are. That number stays small however large the book gets.
"""

import frappe
from frappe import _

from central.billing.projection import outlook
from central.billing.report._currency import split_currency_columns

MONEY_FIELDS = ("outstanding",)


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	rows = outlook.rows(
		on=filters.as_of,
		horizon_days=frappe.utils.cint(filters.horizon_days) or None,
		filters={"currency": filters.currency, "team": filters.team},
	)
	columns = split_currency_columns(get_columns(), rows, MONEY_FIELDS)
	return columns, rows, _note(rows), None, _summary(rows)


def get_columns() -> list[dict]:
	return [
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 150},
		{
			"label": _("Invoice"),
			"fieldname": "invoice",
			"fieldtype": "Link",
			"options": "Invoice",
			"width": 150,
		},
		{
			"label": _("Outstanding"),
			"fieldname": "outstanding",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 110},
		{"label": _("Next action"), "fieldname": "next_action", "fieldtype": "Data", "width": 110},
		{"label": _("On"), "fieldname": "next_action_on", "fieldtype": "Date", "width": 100},
		{"label": _("Suspends on"), "fieldname": "suspends_on", "fieldtype": "Date", "width": 110},
		{"label": _("Due"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Clock starts"), "fieldname": "clock_starts_on", "fieldtype": "Date", "width": 110},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		},
	]


def _summary(rows) -> list[dict]:
	if not rows:
		return []
	deferred = [r for r in rows if r["clock_deferred"]]
	awaiting = [r for r in rows if r["needs_customer_action"]]
	tiles = [
		{"label": _("Unpaid invoices"), "value": len(rows), "datatype": "Int"},
		{"label": _("Awaiting the customer"), "value": len(awaiting), "datatype": "Int"},
		{
			"label": _("Clock deferred by us"),
			"value": len(deferred),
			"datatype": "Int",
			"indicator": "Orange" if deferred else "Green",
		},
	]
	by_currency: dict = {}
	for row in rows:
		by_currency.setdefault(row["currency"], 0.0)
		by_currency[row["currency"]] += frappe.utils.flt(row["outstanding"])
	for currency, total in sorted(by_currency.items()):
		tiles.append(
			{
				"label": _("Outstanding {0}").format(currency),
				"value": total,
				"datatype": "Currency",
				"currency": currency,
			}
		)
	return tiles


def _note(rows) -> str | None:
	deferred = sum(1 for r in rows if r["clock_deferred"])
	if not deferred:
		return None
	# Worth saying out loud: these customers are not late by their own doing.
	return _(
		'<div class="text-muted">{0} of these clocks were pushed forward because '
		"collection failed on our side. Those customers are not late — their escalation "
		"simply restarts later, and the due date is unchanged.</div>"
	).format(deferred)
