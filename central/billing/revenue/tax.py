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

from functools import cached_property

import frappe
from frappe import _
from frappe.utils.translations import N_

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
_STATE_NOT_RECORDED = {"gst_state": None, "gst_state_recorded": 0}


def is_internal_team(team: str) -> bool:
	"""Whether the team is one the company runs for itself, marked on its Billing Profile."""
	return bool(frappe.db.get_value("Billing Profile", team, "is_internal"))


def internal_teams() -> set[str]:
	"""The teams the company runs for itself."""
	return set(frappe.get_all("Billing Profile", filters={"is_internal": 1}, pluck="team"))


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

	if has_zero_rating(p, gst):
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


def with_output_tax(team: str, amount) -> float:
	"""`amount` plus the output tax the team pays on it."""
	amount = frappe.utils.flt(amount)
	return amount + resolve_tax(team, amount)["output_tax_amount"]


def has_zero_rating(profile, gst) -> bool:
	"""Whether the Tax Profile's zero-rating holds. An SEZ supply is zero-rated only to a GSTIN that has not lapsed."""
	return bool(profile.zero_rated) and not (gst.lapsed and profile.zero_rating_reason == "SEZ")


def get_tax_names(team: str) -> dict:
	"""The team's tax today as `tax_label` ("IGST 18%") and `tax_note` ("incl. IGST 18%")."""
	block, names = resolve_tax(team, 100), TaxNames(team)
	return {"tax_label": names.label(block), "tax_note": names.note(block)}


class TaxNames:
	"""Names the GST on one team's amounts, from a tax block: the team's tax today, an
	invoice or a forecast. The rate and the SEZ zero-rating come from the block. IGST or
	CGST + SGST follows the state an invoice was issued with, else the team's state today."""

	def __init__(self, team: str):
		self.team = team

	def label(self, block) -> str | None:
		"""The label: "IGST 18%", "CGST 9% + SGST 9%", "No GST (SEZ)", or None when no GST applies."""
		if block.get("zero_rating_reason") == "SEZ":
			return _("No GST (SEZ)")
		return self._name(block, _LABELS)

	def note(self, block) -> str | None:
		"""What follows an amount that includes the block's tax: "incl. IGST 18%", or
		"SEZ supply, no GST" for a zero-rated supply. None when no GST applies."""
		if block.get("zero_rating_reason") == "SEZ":
			return _("SEZ supply, no GST")
		return self._name(block, _NOTES)

	def paid_label(self, amount, tax_amount) -> str | None:
		"""The GST paid on a top-up of `amount` credit, named from its own `tax_amount`, or
		None when it carried no GST. Never the SEZ label: GST was paid."""
		tax_amount, amount = frappe.utils.flt(tax_amount), frappe.utils.flt(amount)
		if tax_amount <= 0 or amount <= 0:
			return None
		rate = frappe.utils.flt(tax_amount / amount * 100, 1)
		return self._name(
			{"output_tax_type": "GST", "output_tax_amount": tax_amount, "output_tax_rate": rate}, _LABELS
		)

	@staticmethod
	def reason(block) -> str | None:
		"""Why a zero-rated block carries no tax, in words, or None when it is not zero-rated."""
		reason = ZERO_RATING_REASONS.get(block.get("zero_rating_reason") or "")
		return _(reason) if reason else None

	def _name(self, block, names: dict) -> str | None:
		if not has_gst_charged(block):
			return None
		rate = frappe.utils.flt(block.get("output_tax_rate"))
		split = self._split(block)
		return _(names[split]).format(_percent(rate / 2 if split == "CGST" else rate))

	def _split(self, block) -> str:
		"""CGST (in state) or IGST, by the state an invoice was issued with, else the
		team's state today. GST while the company's state is unknown or the team is
		outside India and the block recorded no state."""
		from central.billing.ingester import gst

		if not self._company_code:
			return "GST"
		if self._profile.country != INDIA and not gst.is_state_recorded(block):
			return "GST"
		in_state = gst.is_in_state(gst.filed_state(block, self._profile.state), self._company_code)
		return "CGST" if in_state else "IGST"

	@cached_property
	def _profile(self):
		profile = frappe.db.get_value("Billing Profile", self.team, ["country", "state"], as_dict=True)
		return profile or frappe._dict()

	@cached_property
	def _company_code(self) -> str | None:
		from central.billing.ingester import gst

		return gst.cached_company_state_code()


# Whole phrases, so a translator never joins a label to "incl.".
_LABELS = {
	"GST": N_("GST {0}%"),
	"CGST": N_("CGST {0}% + SGST {0}%"),
	"IGST": N_("IGST {0}%"),
}
_NOTES = {
	"GST": N_("incl. GST {0}%"),
	"CGST": N_("incl. CGST {0}% + SGST {0}%"),
	"IGST": N_("incl. IGST {0}%"),
}

# The fields of a stored invoice that `TaxNames` reads.
LABEL_FIELDS = (
	"output_tax_type",
	"output_tax_rate",
	"output_tax_amount",
	"zero_rating_reason",
	"gst_state",
	"gst_state_recorded",
)

ZERO_RATING_REASONS = {
	"SEZ": N_("Zero-rated supply to a Special Economic Zone (SEZ) unit."),
	"Overseas": N_("Zero-rated export of services outside India."),
}


def gst_state_at_issue(team: str, block) -> dict:
	"""The team's billing state to record on an invoice with this tax `block` as it is issued.
	Recorded only when it charges GST in India; a team with no state is recorded with none."""
	if not has_gst_charged(block):
		return dict(_STATE_NOT_RECORDED)
	profile = frappe.db.get_value("Billing Profile", {"team": team, "country": INDIA}, "state", as_dict=True)
	if not profile:
		return dict(_STATE_NOT_RECORDED)
	return {"gst_state": profile.state or None, "gst_state_recorded": 1}


def has_gst_charged(block) -> bool:
	"""Whether a tax block or an invoice charges GST."""
	return block.get("output_tax_type") == "GST" and bool(frappe.utils.flt(block.get("output_tax_amount")))


def _percent(rate: float) -> str:
	return f"{frappe.utils.flt(rate, 2):g}"


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
