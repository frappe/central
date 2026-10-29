# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""New signups & billing activations — the acquisition-to-revenue funnel.

One row per team that signed up in the window, with the billing milestones it has
crossed: billing profile created, first payment method added, and first payment
(the activation event that turns a signup into revenue). A first payment is money
the customer paid: an invoice paid by the gateway or by paid-in credit, or a credit
top-up. An invoice that welcome credit alone covered is not a payment. The stage is
derived from the furthest milestone reached:

  Signed Up  → team exists, no billing profile yet
  Onboarding → profile and/or a payment method, but no payment
  Activated  → has paid money at least once

The summary cards headline signups, activations, and the activation rate over the
window. "Signup" is the team's creation (top of funnel); the milestones are the
earliest billing record of each kind for that team.
"""

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.doctype.payment_method.payment_method import held_method_filters
from central.billing.report._currency import split_currency_columns
from central.billing.report._paging import first_rows


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows, summary = get_data(filters)
	columns = split_currency_columns(columns, rows, ["first_payment_amount"])
	rows, message = first_rows(rows)
	return columns, rows, message, None, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 130},
		{"label": _("Team Name"), "fieldname": "team_name", "fieldtype": "Data", "width": 180},
		{"label": _("Signed Up"), "fieldname": "signed_up", "fieldtype": "Datetime", "width": 160},
		{
			"label": _("Profile Created"),
			"fieldname": "profile_created",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80},
		{
			"label": _("First Payment Method"),
			"fieldname": "first_method",
			"fieldtype": "Datetime",
			"width": 160,
		},
		{"label": _("First Paid"), "fieldname": "first_paid", "fieldtype": "Datetime", "width": 160},
		{
			"label": _("First Payment"),
			"fieldname": "first_payment_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 110},
	]


def _earliest_by_team(
	doctype: str,
	teams: list[str],
	extra_filters: dict | None = None,
	extra_fields: list[str] | None = None,
	time_field: str = "creation",
	or_filters: dict | None = None,
) -> dict[str, dict]:
	"""Earliest row of `doctype` per team by `time_field`, keyed by team. Its time is `at`."""
	conditions = {"team": ["in", teams], time_field: ["is", "set"]}
	if extra_filters:
		conditions.update(extra_filters)
	rows = frappe.get_all(
		doctype,
		filters=conditions,
		fields=["team", f"{time_field} as at", *(extra_fields or [])],
		order_by=f"{time_field} asc",
		or_filters=or_filters,
	)
	first: dict[str, dict] = {}
	for r in rows:
		first.setdefault(r.team, r)  # first seen is earliest given the asc order
	return first


def _first_payment_by_team(teams: list[str]) -> dict[str, dict]:
	"""Each team's first money, keyed by team, with its amount and currency."""
	paid_invoice = {"status": "Paid", "invoice_type": "Billable"}
	sources = (
		_earliest_by_team(
			"Invoice",
			teams,
			{**paid_invoice, "amount_paid": [">", 0]},
			["amount_paid as amount", "currency"],
			time_field="paid_at",
		),
		_earliest_by_team(
			"Invoice",
			teams,
			{**paid_invoice, "advance_applied": [">", 0]},
			["advance_applied as amount", "currency"],
			time_field="paid_at",
		),
		_earliest_by_team(
			"Credit Ledger Entry", teams, {"entry_type": "Credit", "paid_in": 1}, ["amount", "currency"]
		),
	)
	first: dict[str, dict] = {}
	for source in sources:
		for team, row in source.items():
			if team not in first or row.at < first[team].at:
				first[team] = row
	return first


def get_data(filters: dict):
	conditions = {}
	if filters.get("from_date") and filters.get("to_date"):
		conditions["creation"] = ["between", [filters["from_date"], filters["to_date"]]]
	elif filters.get("from_date"):
		conditions["creation"] = [">=", filters["from_date"]]
	elif filters.get("to_date"):
		conditions["creation"] = ["<=", filters["to_date"]]

	teams = frappe.get_all(
		"Team",
		filters=conditions,
		fields=["name", "team_name", "creation"],
		order_by="creation desc",
	)
	if not teams:
		return [], _empty_summary()

	names = [t.name for t in teams]
	profiles = _earliest_by_team("Billing Profile", names, extra_fields=["currency"])
	methods = _earliest_by_team("Payment Method", names, or_filters=held_method_filters())
	paid = _first_payment_by_team(names)

	rows = []
	signups = onboarding = activated = 0
	for t in teams:
		profile = profiles.get(t.name)
		method = methods.get(t.name)
		first_paid = paid.get(t.name)
		if first_paid:
			stage = "Activated"
			activated += 1
		elif profile or method:
			stage = "Onboarding"
			onboarding += 1
		else:
			stage = "Signed Up"
		signups += 1
		rows.append(
			{
				"team": t.name,
				"team_name": t.team_name,
				"signed_up": t.creation,
				"profile_created": profile.at if profile else None,
				"currency": (profile.currency if profile else None)
				or (first_paid.currency if first_paid else None),
				"first_method": method.at if method else None,
				"first_paid": first_paid.at if first_paid else None,
				"first_payment_amount": flt(first_paid.amount) if first_paid else None,
				"stage": stage,
			}
		)

	rate = (activated / signups * 100) if signups else 0.0
	summary = [
		{"label": _("Signups"), "value": signups, "datatype": "Int"},
		{"label": _("Onboarding"), "value": onboarding, "datatype": "Int", "indicator": "orange"},
		{"label": _("Activated"), "value": activated, "datatype": "Int", "indicator": "green"},
		{
			"label": _("Activation Rate"),
			"value": round(rate, 2),
			"datatype": "Percent",
			"indicator": "green" if rate >= 40 else "orange" if rate >= 15 else "red",
		},
	]
	return rows, summary


def _empty_summary() -> list[dict]:
	return [
		{"label": _("Signups"), "value": 0, "datatype": "Int"},
		{"label": _("Onboarding"), "value": 0, "datatype": "Int", "indicator": "orange"},
		{"label": _("Activated"), "value": 0, "datatype": "Int", "indicator": "green"},
		{"label": _("Activation Rate"), "value": 0, "datatype": "Percent"},
	]
