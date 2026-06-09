# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Tax — three structurally different mechanics, not one rate (issue #13).

  - Additive output tax (GST/VAT) — added to `total`; the customer pays more.
  - Zero-rating with reason (SEZ-LUT/export) — tax 0 *plus* a compliance reason
    code (never a bare "none" — an auditor will ask).
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

_ZERO_BLOCK = {
	"output_tax_type": "none",
	"output_tax_rate": 0,
	"output_tax_amount": 0,
	"zero_rating_reason": None,
	"tds_applicable": 0,
	"tds_rate": 0,
	"tds_amount": 0,
}


def resolve_tax(team: str, subtotal) -> dict:
	"""The invoice tax block for a team's taxable subtotal.

	Reads the team's Tax Profile; a team with no profile is untaxed (the launch
	default — output tax 0, no withholding).
	"""
	subtotal = frappe.utils.flt(subtotal)
	if not frappe.db.exists("Tax Profile", team):
		return dict(_ZERO_BLOCK)

	p = frappe.get_doc("Tax Profile", team)
	block = dict(_ZERO_BLOCK)
	block["output_tax_type"] = p.output_tax_type or "none"
	block["output_tax_rate"] = frappe.utils.flt(p.output_tax_rate)

	if p.zero_rated:
		# Zero-rated WITH a reason — the tax is 0 but auditable.
		if not p.zero_rating_reason:
			frappe.throw(
				"Zero-rated team has no zero_rating_reason.", frappe.ValidationError
			)
		block["zero_rating_reason"] = p.zero_rating_reason
		block["output_tax_amount"] = 0
	else:
		block["output_tax_amount"] = frappe.utils.flt(subtotal * block["output_tax_rate"] / 100, 2)

	if p.tds_applicable:
		block["tds_applicable"] = 1
		block["tds_rate"] = frappe.utils.flt(p.tds_rate)
		block["tds_amount"] = frappe.utils.flt(subtotal * block["tds_rate"] / 100, 2)

	return block


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
