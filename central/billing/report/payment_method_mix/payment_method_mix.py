# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment method mix, mandate coverage & settlement via credits.

Two things a DRI reads off one page:

1. **The instrument mix** — one row per configured method type (Card / UPI Autopay /
   Prepaid Credits) with a status breakdown, so you can read how many methods are
   Active vs Paused/Expired/Failed and how many need re-auth. The summary cards
   headline mandate coverage — the share of teams (with any payment method) that
   hold an Active recurring mandate — the key signal for whether off-session
   collection will work.

2. **Payments via credits** — how much invoice value was settled from the wallet,
   split by where the credit came from: **Welcome** (free promotional grants) vs
   **Purchased** (customer top-ups). This is the piece card/UPI totals miss: a bill
   paid from the wallet never creates a Payment Attempt, so without these rows the
   "mix" undercounts credit settlement entirely.

Credit origin comes from `Credit Ledger Entry.reference_type`: `Promotion` is a
welcome grant, `Top-up`/`Payment Method` is a purchase. A settlement is a `Debit`
referencing an `Invoice`. Because a wallet is a **fungible pool** — a debit doesn't
name the lot it drew from — applied credit is attributed to origin **proportionally
to each team's welcome:purchased funding ratio**, per currency. Amounts are always
per currency (a wallet holds one currency per team); never summed across currencies.
"""

import frappe
from frappe import _

from central.billing.report._currency import split_currency_columns

STATUS_FIELDS = [
	("active", "Active"),
	("paused", "Paused"),
	("pending", "Pending Validation"),
	("expired", "Expired"),
	("cancelled", "Cancelled"),
	("failed", "Failed"),
]
MANDATE_TYPES = {"UPI Autopay", "Card"}  # method types that can carry a recurring mandate

WELCOME_REFS = {"Promotion"}
PURCHASED_REFS = {"Top-up", "Payment Method"}


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows, summary, chart = get_data(filters)
	columns = split_currency_columns(columns, rows, ["credits_applied"])
	message = _(
		"Applied credit is attributed to Welcome vs Purchased in proportion to each "
		"team's credit funding (a wallet is a fungible pool)."
	)
	return columns, rows, message, chart, summary


def get_columns() -> list[dict]:
	cols = [
		{"label": _("Payment Source"), "fieldname": "method_type", "fieldtype": "Data", "width": 170},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90},
	]
	for fieldname, label in STATUS_FIELDS:
		cols.append({"label": _(label), "fieldname": fieldname, "fieldtype": "Int", "width": 110})
	cols.append({"label": _("Default"), "fieldname": "is_default", "fieldtype": "Int", "width": 90})
	cols.append(
		{"label": _("Re-auth Needed"), "fieldname": "reauth_required", "fieldtype": "Int", "width": 120}
	)
	cols.append(
		{
			"label": _("Credits Applied"),
			"fieldname": "credits_applied",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		}
	)
	cols.append({"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 80})
	return cols


def get_data(filters: dict):
	method_rows, method_summary = _method_mix(filters)
	credit_rows, credit_summary = _credit_settlement(filters)

	rows = method_rows + credit_rows
	summary = method_summary + credit_summary
	chart = None
	if rows:
		chart = {
			"data": {
				"labels": [r["method_type"] for r in rows],
				"datasets": [{"name": _("Total"), "values": [r["total"] for r in rows]}],
			},
			"type": "pie",
		}
	return rows, summary, chart


def _method_mix(filters: dict):
	"""The instrument inventory — one row per configured method type, by status."""
	conditions = {}
	if filters.get("team"):
		conditions["team"] = filters["team"]
	if filters.get("gateway"):
		conditions["gateway"] = filters["gateway"]

	methods = frappe.get_all(
		"Payment Method",
		filters=conditions,
		fields=["team", "method_type", "status", "is_default", "reauth_required"],
	)

	status_to_field = {label: fieldname for fieldname, label in STATUS_FIELDS}
	agg: dict[str, dict] = {}
	teams_with_method = set()
	teams_with_mandate = set()
	for m in methods:
		mt = m.method_type or _("(unset)")
		g = agg.setdefault(mt, {fieldname: 0 for fieldname, _l in STATUS_FIELDS})
		g["total"] = g.get("total", 0) + 1
		field = status_to_field.get(m.status)
		if field:
			g[field] += 1
		if m.is_default:
			g["is_default"] = g.get("is_default", 0) + 1
		if m.reauth_required:
			g["reauth_required"] = g.get("reauth_required", 0) + 1
		teams_with_method.add(m.team)
		if m.status == "Active" and m.method_type in MANDATE_TYPES:
			teams_with_mandate.add(m.team)

	rows = []
	for mt, g in sorted(agg.items()):
		rows.append(
			{
				"method_type": mt,
				"total": g.get("total", 0),
				"is_default": g.get("is_default", 0),
				"reauth_required": g.get("reauth_required", 0),
				"currency": "",
				**{fieldname: g[fieldname] for fieldname, _l in STATUS_FIELDS},
			}
		)
	rows.sort(key=lambda r: r["total"], reverse=True)

	coverage = (len(teams_with_mandate) / len(teams_with_method) * 100) if teams_with_method else 0.0
	summary = [
		{"label": _("Payment Methods"), "value": len(methods), "datatype": "Int"},
		{"label": _("Teams w/ Method"), "value": len(teams_with_method), "datatype": "Int"},
		{
			"label": _("Teams w/ Active Mandate"),
			"value": len(teams_with_mandate),
			"datatype": "Int",
			"indicator": "green",
		},
		{
			"label": _("Mandate Coverage"),
			"value": round(coverage, 2),
			"datatype": "Percent",
			"indicator": "green" if coverage >= 70 else "orange" if coverage >= 40 else "red",
		},
	]
	return rows, summary


def _credit_settlement(filters: dict):
	"""Credits applied to invoices, split Welcome vs Purchased, per currency.

	Attribution is proportional to each team's welcome:purchased funding, since a
	wallet is a fungible pool and a settlement debit carries no origin. Teams with
	applied credit but no tracked welcome/purchased funding (e.g. only refund/admin
	credits) fall to Purchased — never Welcome, so the free-credit figure is never
	overstated.
	"""
	conditions = {}
	if filters.get("team"):
		conditions["team"] = filters["team"]

	entries = frappe.get_all(
		"Credit Ledger Entry",
		filters=conditions,
		fields=["team", "currency", "entry_type", "reference_type", "amount"],
	)

	# Per (team, currency): welcome/purchased funding and total applied.
	funding: dict[tuple, dict] = {}
	for e in entries:
		currency = (e.currency or "").strip()
		if not currency:
			continue
		f = funding.setdefault((e.team, currency), {"welcome": 0.0, "purchased": 0.0, "applied": 0.0})
		amount = frappe.utils.flt(e.amount)
		if e.entry_type == "Credit" and e.reference_type in WELCOME_REFS:
			f["welcome"] += amount
		elif e.entry_type == "Credit" and e.reference_type in PURCHASED_REFS:
			f["purchased"] += amount
		elif e.entry_type == "Debit" and e.reference_type == "Invoice":
			f["applied"] += amount

	# Attribute each team's applied credit to origin, then roll up per currency.
	per_currency: dict[str, dict] = {}
	for (team, currency), f in funding.items():
		c = per_currency.setdefault(
			currency,
			{
				"welcome_applied": 0.0,
				"purchased_applied": 0.0,
				"welcome_teams": set(),
				"purchased_teams": set(),
			},
		)
		if f["welcome"] > 0:
			c["welcome_teams"].add(team)
		if f["purchased"] > 0:
			c["purchased_teams"].add(team)
		if f["applied"] <= 0:
			continue
		denom = f["welcome"] + f["purchased"]
		welcome_share = (f["welcome"] / denom) if denom > 0 else 0.0
		c["welcome_applied"] += f["applied"] * welcome_share
		c["purchased_applied"] += f["applied"] * (1 - welcome_share)

	rows = []
	total_welcome_teams: set = set()
	total_purchased_teams: set = set()
	for currency in sorted(per_currency):
		c = per_currency[currency]
		total_welcome_teams |= c["welcome_teams"]
		total_purchased_teams |= c["purchased_teams"]
		rows.append(
			_credit_row(
				_("Welcome Credits"), len(c["welcome_teams"]), round(c["welcome_applied"], 2), currency
			)
		)
		rows.append(
			_credit_row(
				_("Purchased Credits"), len(c["purchased_teams"]), round(c["purchased_applied"], 2), currency
			)
		)

	summary = [
		{"label": _("Welcome-Funded Teams"), "value": len(total_welcome_teams), "datatype": "Int"},
		{"label": _("Credit-Buying Teams"), "value": len(total_purchased_teams), "datatype": "Int"},
	]
	return rows, summary


def _credit_row(source: str, teams: int, applied: float, currency: str) -> dict:
	"""A credit-origin row. Status columns are N/A for credits, so left blank."""
	row = {fieldname: None for fieldname, _l in STATUS_FIELDS}
	row.update(
		{
			"method_type": source,
			"total": teams,
			"is_default": None,
			"reauth_required": None,
			"credits_applied": applied,
			"currency": currency,
		}
	)
	return row
