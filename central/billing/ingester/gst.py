# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How GST applies to a team's documents in the accounting system.

The advance and the invoice both read it from here, so the tax on money received
up front always matches the tax on the invoice it later pays.
"""

import frappe

from central.billing.india_gst import INDIA, state_code
from central.billing.ingester import connection
from central.billing.ingester.settings import accounting_settings

OVERSEAS_PLACE_OF_SUPPLY = "96-Other Countries"


def treatment(team: str) -> frappe._dict:
	"""GSTIN, GST category, place of supply, and the tax template (None: no GST)."""
	from central.billing.revenue import gst_status

	profile = (
		frappe.db.get_value("Billing Profile", team, ["country", "state", "gst_category"], as_dict=True)
		or frappe._dict()
	)
	if profile.country != INDIA:
		return frappe._dict(
			gstin="", gst_category="Overseas", place_of_supply=OVERSEAS_PLACE_OF_SUPPLY, template=None
		)

	gstin = gst_status.standing(team).gstin or ""
	code = state_code(profile.state)
	place_of_supply = f"{code}-{profile.state}" if code else None
	if _zero_rated_sez(team):
		return frappe._dict(gstin=gstin, gst_category="SEZ", place_of_supply=place_of_supply, template=None)

	settings = accounting_settings()
	in_state = code and code == company_state_code()
	return frappe._dict(
		gstin=gstin,
		gst_category=(profile.gst_category or "Registered Regular") if gstin else "Unregistered",
		place_of_supply=place_of_supply,
		template=settings.in_state_template if in_state else settings.out_state_template,
	)


def tax_rows(template: str | None, paid_amount: float | None = None) -> list[dict]:
	"""The template's GST rows, for a Sales Invoice, or for an advance of `paid_amount`.

	An advance carries GST inside what was paid, and each row is sent with its
	amount worked out. The accounting system sets aside the customer's share before
	it computes tax, so rows without amounts would credit them the whole payment.
	"""
	if not template:
		return []
	rows = (connection.fetch("Sales Taxes and Charges Template", template) or {}).get("taxes") or []
	if paid_amount is None:
		return [
			{
				"account_head": r["account_head"],
				"rate": r["rate"],
				"description": r.get("description"),
				"charge_type": "On Net Total",
			}
			for r in rows
		]
	taxable = frappe.utils.flt(paid_amount) / (1 + sum(frappe.utils.flt(r["rate"]) for r in rows) / 100)
	shaped = []
	for row in rows:
		amount = frappe.utils.flt(taxable * frappe.utils.flt(row["rate"]) / 100, 2)
		shaped.append(
			{
				"account_head": row["account_head"],
				"rate": row["rate"],
				"description": row.get("description"),
				"charge_type": "On Paid Amount",
				"included_in_paid_amount": 1,
				"tax_amount": amount,
				"base_tax_amount": amount,
			}
		)
	return shaped


def company_gstin() -> str:
	address = connection.fetch("Address", accounting_settings().company_address) or {}
	return address.get("gstin") or ""


def company_state_code() -> str:
	return company_gstin()[:2]


def _zero_rated_sez(team: str) -> bool:
	return bool(
		frappe.db.get_value("Tax Profile", {"team": team, "zero_rated": 1, "zero_rating_reason": "SEZ"})
	)
