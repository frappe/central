# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How GST applies to a team's documents in the accounting system.

The advance and the invoice both read it from here, so the tax on money received
up front always matches the tax on the invoice it later pays.
"""

import frappe
import requests

from central.billing.india_gst import INDIA, state_code
from central.billing.ingester import connection
from central.billing.ingester.settings import accounting_settings

OVERSEAS_PLACE_OF_SUPPLY = "96-Other Countries"
COMPANY_STATE_KEY = "billing:company_state_code"
LAST_COMPANY_STATE_KEY = "billing:company_state_code:last"
# Set after a failed read, so screens do not call the accounting system on every view.
MISSED_COMPANY_STATE_KEY = "billing:company_state_code:missed"
COMPANY_STATE_TTL = 24 * 60 * 60
# After a failed read, the last known code is reused this long before trying again.
RETRY_AFTER = 60 * 60


def treatment(team: str, charged_tax: float | None = None, invoice=None) -> frappe._dict:
	"""GSTIN, GST category, place of supply, and the tax template (None: no GST).

	`charged_tax` is the GST already on the document. When given, it decides the template,
	so the filing matches what was charged even if the team's standing changed since.
	`invoice` gives the state it was issued with. The place of supply and the template both
	follow that state, so a later change to the team's state does not change the filing.
	"""
	from central.billing.revenue import gst_status

	profile = (
		frappe.db.get_value("Billing Profile", team, ["country", "state", "gst_category"], as_dict=True)
		or frappe._dict()
	)
	if profile.country != INDIA and not is_state_recorded(invoice):
		return frappe._dict(
			gstin="", gst_category="Overseas", place_of_supply=OVERSEAS_PLACE_OF_SUPPLY, template=None
		)

	gstin = gst_status.standing(team).gstin or ""
	state = filed_state(invoice, profile.state)
	place_of_supply = _place_of_supply(state)
	if _is_untaxed(team, charged_tax):
		return frappe._dict(gstin=gstin, gst_category="SEZ", place_of_supply=place_of_supply, template=None)

	return frappe._dict(
		gstin=gstin,
		gst_category=(profile.gst_category or "Registered Regular") if gstin else "Unregistered",
		place_of_supply=place_of_supply,
		template=_template_for_state(state),
	)


def is_state_recorded(invoice) -> bool:
	"""Whether the invoice recorded the team's state when it was issued (a blank state counts)."""
	return bool(invoice and invoice.get("gst_state_recorded"))


def filed_state(invoice, current_state: str | None) -> str | None:
	"""The state an invoice's GST is filed under: the one recorded at issue, else the team's current one."""
	return (invoice.get("gst_state") or None) if is_state_recorded(invoice) else current_state


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


def is_in_state(state: str | None, company_code: str | None = None) -> bool:
	"""Whether a supply to `state` stays in the company's own state (CGST + SGST, not IGST).
	The company's state is read live unless `company_code` is given."""
	code = state_code(state)
	return bool(code) and code == (company_code or company_state_code())


def cached_company_state_code() -> str | None:
	"""The company's GST state code, read from the accounting system at most once a day.
	The last known code when a read fails; None when it was never known."""
	code = frappe.cache.get_value(COMPANY_STATE_KEY, use_local_cache=False)
	if code:
		return code
	code = _read_company_state_code()
	if code:
		frappe.cache.set_value(LAST_COMPANY_STATE_KEY, code)
		frappe.cache.set_value(COMPANY_STATE_KEY, code, expires_in_sec=COMPANY_STATE_TTL)
		return code
	last = frappe.cache.get_value(LAST_COMPANY_STATE_KEY, use_local_cache=False)
	if last:
		frappe.cache.set_value(COMPANY_STATE_KEY, last, expires_in_sec=RETRY_AFTER)
	return last


def company_gstin() -> str:
	address = connection.fetch("Address", accounting_settings().company_address) or {}
	return address.get("gstin") or ""


def company_state_code() -> str:
	return company_gstin()[:2]


def _read_company_state_code() -> str | None:
	if not connection.enabled() or frappe.cache.get_value(MISSED_COMPANY_STATE_KEY, use_local_cache=False):
		return None
	try:
		return company_state_code() or None
	except (requests.RequestException, connection.NoAccess):
		frappe.log_error(title="Company GST state could not be read")
		frappe.cache.set_value(MISSED_COMPANY_STATE_KEY, 1, expires_in_sec=RETRY_AFTER)
		return None


def _place_of_supply(state: str | None) -> str | None:
	code = state_code(state)
	return f"{code}-{state}" if code else None


def _template_for_state(state: str | None) -> str:
	settings = accounting_settings()
	return settings.in_state_template if is_in_state(state) else settings.out_state_template


def _is_untaxed(team: str, charged_tax: float | None) -> bool:
	if charged_tax is None:
		return _is_zero_rated_sez(team)
	return not frappe.utils.flt(charged_tax)


def _is_zero_rated_sez(team: str) -> bool:
	"""The rule the invoice tax uses, so what is filed matches what is charged."""
	from central.billing.revenue import gst_status, tax

	profile = frappe.db.get_value(
		"Tax Profile",
		{"team": team, "zero_rating_reason": "SEZ"},
		["zero_rated", "zero_rating_reason"],
		as_dict=True,
	)
	return bool(profile) and tax.has_zero_rating(profile, gst_status.standing(team))
