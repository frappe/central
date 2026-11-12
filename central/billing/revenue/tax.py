# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Tax — three structurally different mechanics, not one rate (issue #13).

  - Additive output tax (GST/VAT) — added to `total`; the customer pays more.
  - Zero-rating with reason (SEZ-LUT/export) — tax 0 *plus* a compliance reason
    code (never a bare "None" — an auditor will ask).
  - Withholding (TDS) — reduces what is *collected*, not `total`; the customer
    pays less and supplies a certificate.

So:  total = subtotal + output_tax_amount
     expected_collection = total - tds_amount  (further reduced by credits at open)
     paid  <=>  amount_paid >= expected_collection

GST + SEZ ship fully; the TDS *seam* (withholding-aware expected_collection +
paid-state) lands now so adding TDS later is additive, not a rewrite. tds_amount
is 0 at launch (no team self-declares yet).
"""

import frappe
from frappe import _

from central.billing import settings
from central.billing.india_gst import INDIA
from central.billing.revenue import gst_status

_ZERO_BLOCK = {
	"output_tax_type": "None",
	"output_tax_rate": 0,
	"output_tax_amount": 0,
	"zero_rating_reason": None,
	"tds_applicable": 0,
	"tds_rate": 0,
	"tds_amount": 0,
	"customer_gstin": None,
}


def is_internal_team(team: str) -> bool:
	"""Whether the team is one the company runs for itself, marked on its Billing Profile."""
	return bool(frappe.db.get_value("Billing Profile", team, "is_internal"))


def is_indian_team(team: str) -> bool:
	"""Whether the team is billed in India, by its billing country or its INR currency."""
	profile = frappe.db.get_value("Billing Profile", team, ["country", "currency"], as_dict=True)
	if not profile:
		return False
	return (profile.country or "").strip() == INDIA or profile.currency == "INR"


def get_country_output_tax(team: str) -> dict:
	"""The output tax the team's billing country implies: GST in India, none elsewhere."""
	if is_indian_team(team):
		return {"output_tax_type": "GST", "output_tax_rate": settings.default_gst_rate()}
	return {"output_tax_type": "None", "output_tax_rate": 0}


def resolve_tax(team: str, subtotal) -> dict:
	"""The invoice tax block for a team's taxable subtotal.

	Reads the team's Tax Profile. A team with no profile is taxed by its country:
	GST at the default rate in India, no tax elsewhere. A GSTIN the GST portal calls
	lapsed is left off, and the team is billed as unregistered.
	"""
	subtotal = frappe.utils.flt(subtotal)
	gst = gst_status.standing(team)
	block = dict(_ZERO_BLOCK, customer_gstin=gst.gstin)
	# An internal team's usage is waived, not sold, so there is no supply to tax.
	if is_internal_team(team):
		return block

	# GST is mandatory in India, so a missing profile must not bill an Indian team untaxed.
	p = _get_tax_profile(team)
	block["output_tax_type"] = p.output_tax_type or "None"
	block["output_tax_rate"] = frappe.utils.flt(p.output_tax_rate)

	# An SEZ supply is zero-rated only to a live GSTIN; a lapsed one is taxed.
	if p.zero_rated and not (gst.lapsed and p.zero_rating_reason == "SEZ"):
		# Zero-rated WITH a reason — the tax is 0 but auditable.
		if not p.zero_rating_reason:
			frappe.throw(_("Zero-rated team has no zero-rating reason."), frappe.ValidationError)
		block["zero_rating_reason"] = p.zero_rating_reason
		block["output_tax_amount"] = 0
	else:
		block["output_tax_amount"] = frappe.utils.flt(subtotal * block["output_tax_rate"] / 100, 2)

	if p.tds_applicable:
		block["tds_applicable"] = 1
		block["tds_rate"] = frappe.utils.flt(p.tds_rate)
		block["tds_amount"] = frappe.utils.flt(subtotal * block["tds_rate"] / 100, 2)

	return block


def _get_tax_profile(team: str):
	if frappe.db.exists("Tax Profile", team):
		return frappe.get_doc("Tax Profile", team)
	return frappe._dict(get_country_output_tax(team))


def is_paid(invoice) -> bool:
	"""`paid` <=> amount_paid >= expected_collection.

	The certificate gate is trivially satisfied when nothing is withheld, so a
	TDS customer who legally short-pays is not marked permanently unpaid.
	"""
	withheld = frappe.utils.flt(invoice.tds_amount) > 0
	covered = frappe.utils.flt(invoice.amount_paid) >= frappe.utils.flt(invoice.expected_collection)
	return covered and (not withheld or bool(invoice.tds_certificate_received))


def mandate_ceiling_amount(invoice) -> float:
	"""The figure a mandate ceiling is checked against — the gross `total`, never
	the TDS-reduced collected amount (the mandate was authorised for the gross)."""
	return frappe.utils.flt(invoice.total)
