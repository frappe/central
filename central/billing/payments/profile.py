# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""
Billing Profile read/write helpers for a team.

The gateway-customer logic (mint-or-reuse a customer id per team+gateway, stored
in a Gateway Customer row and committed before the order so a partial setup never
orphans it) lives in central.billing.payments.payments.ensure_gateway_customer —
the single place both the top-up and payment-method flows provision through.
"""

import frappe
from frappe import _

from central.billing.india_gst import INDIA

# A save that carries any of these is the customer editing their billing address.
ADDRESS_FIELDS = ("address_line1", "address_line2", "city", "state", "pincode")


def create_or_update_billing_profile(team: str, **values):
	"""Creates or updates the billing profile for the team and returns the doc."""
	if frappe.db.exists("Billing Profile", team):
		doc = frappe.get_doc("Billing Profile", team)
		doc.update(values)
	else:
		doc = frappe.get_doc({"doctype": "Billing Profile", "team": team, **values})
	_require_indian_state(doc, values)
	doc.save(ignore_permissions=True)
	return doc


def get_billing_profile(team: str):
	"""Returns the billing profile for the team."""
	return frappe.get_doc("Billing Profile", team)


def is_state_missing(team: str) -> bool:
	"""Whether an Indian team has no state on its profile, so its GST is charged as IGST."""
	from central.billing.revenue.tax import is_indian_team

	state = frappe.db.get_value("Billing Profile", team, "state")
	return is_indian_team(team) and not (state or "").strip()


def igst_rate(team: str) -> float | None:
	"""The GST rate charged, as IGST, to an Indian team with no state; None once it has one,
	or when it is charged no GST (zero-rated or internal)."""
	from central.billing.revenue.tax import resolve_tax

	if not is_state_missing(team):
		return None
	return resolve_tax(team, 100)["output_tax_amount"] or None


def _require_indian_state(doc, values: dict) -> None:
	"""An Indian billing address the customer saves names its state.

	Only the customer's own address edit is checked, so a profile saved without a
	state before this rule, or a save of the country alone, still goes through.
	"""
	if doc.country != INDIA or (doc.state or "").strip():
		return
	if not any(field in values for field in ADDRESS_FIELDS):
		return
	frappe.throw(_("Select your state. The GST on your bills depends on it."), frappe.ValidationError)
