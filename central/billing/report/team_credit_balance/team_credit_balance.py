# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Available credit balance per team.

Sourced from the Credit Wallet anchor row (one per team), whose `balance` is kept
in lockstep with the newest Credit Ledger Entry's running balance — so it is the
authoritative, already-computed available balance without re-summing the ledger.
The team's low-balance threshold (Billing Profile.min_balance) is joined in to flag
wallets that have run below it.
"""

import frappe
from frappe import _

from central.billing.report._currency import split_currency_columns


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	columns = split_currency_columns(columns, data, ["balance", "min_balance"])
	return columns, data


def get_columns() -> list[dict]:
	return [
		{
			"label": _("Team"),
			"fieldname": "team",
			"fieldtype": "Link",
			"options": "Team",
			"width": 200,
		},
		{
			"label": _("Team Name"),
			"fieldname": "team_name",
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Data",
			"width": 90,
		},
		{
			"label": _("Available Balance"),
			"fieldname": "balance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"label": _("Low-Balance Threshold"),
			"fieldname": "min_balance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 170,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 100,
		},
	]


def get_data(filters: dict) -> list[dict]:
	wallet_filters = {}
	if filters.get("team"):
		wallet_filters["team"] = filters["team"]

	wallets = frappe.get_all(
		"Credit Wallet",
		filters=wallet_filters,
		fields=["team", "currency", "balance"],
		order_by="balance asc",
	)
	if not wallets:
		return []

	teams = [w.team for w in wallets]
	# One query each for the display name and the low-balance threshold, keyed by team.
	team_names = dict(
		frappe.get_all("Team", filters={"name": ["in", teams]}, fields=["name", "team_name"], as_list=True)
	)
	thresholds = dict(
		frappe.get_all(
			"Billing Profile",
			filters={"team": ["in", teams]},
			fields=["team", "min_balance"],
			as_list=True,
		)
	)

	rows = []
	for w in wallets:
		min_balance = frappe.utils.flt(thresholds.get(w.team))
		balance = frappe.utils.flt(w.balance)
		# "Low" only when a positive threshold is configured and the wallet is under it.
		status = "Low" if min_balance and balance < min_balance else "OK"
		rows.append({
			"team": w.team,
			"team_name": team_names.get(w.team),
			"currency": w.currency or "INR",
			"balance": balance,
			"min_balance": min_balance,
			"status": status,
		})
	return rows
