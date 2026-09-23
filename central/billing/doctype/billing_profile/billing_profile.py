# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.catalog.subscriptions import team_active_segments
from central.billing.india_gst import GST_STATE_CODES, INDIA

# Once a team has been invoiced, these are frozen: invoices are denominated in the
# currency and taxed by the country in force when they were issued, so changing
# either would desync documents already sent to the customer.
_INVOICE_LOCKED_FIELDS = {"country": "country", "currency": "currency"}

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
REQUIRED_FIELDS = ("currency", "legal_name", "address_line1", "city", "country")
FIELD_LABELS = {
	"currency": "currency",
	"legal_name": "legal name",
	"address_line1": "address line 1",
	"city": "city",
	"country": "country",
}


def validate_gstin(gstin: str) -> bool:
	return bool(GSTIN_RE.match((gstin or "").strip().upper()))


def get_team_currency(team: str) -> str:
	"""Return the billing profile currency, with the legacy segment fallback."""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if currency:
		return currency

	segment_currency = next((row.currency for row in team_active_segments(team) if row.currency), None)
	return segment_currency or "INR"


def get_missing_fields(team: str) -> list[str]:
	if not frappe.db.exists("Billing Profile", team):
		return list(REQUIRED_FIELDS)

	profile = frappe.get_doc("Billing Profile", team)
	return [field for field in REQUIRED_FIELDS if not str(profile.get(field) or "").strip()]


def get_missing_field_labels(team: str) -> list[str]:
	return [FIELD_LABELS.get(field, field) for field in get_missing_fields(team)]


def is_complete(team: str) -> bool:
	return not get_missing_fields(team)


def require_billing_profile(team: str, action: str) -> None:
	"""Require a complete legal and currency profile before a billable action."""
	missing = get_missing_field_labels(team)
	if missing:
		frappe.throw(
			_("Complete your billing profile before you can {0}. Missing: {1}.").format(
				action, ", ".join(missing)
			),
			frappe.ValidationError,
		)


class BillingProfile(Document):
	def validate(self):
		self.validate_gstin()
		self.validate_india_state()
		self.lock_country_and_currency_after_invoicing()

	def lock_country_and_currency_after_invoicing(self):
		"""Freeze country and currency once the team has been invoiced.

		A backstop that holds no matter how the profile is saved (dashboard, admin,
		script); the dashboard also locks currency on any money activity. Legal name,
		address and GSTIN stay editable — only the two invoice-defining fields lock."""
		if self.is_new():
			return

		changed = [label for field, label in _INVOICE_LOCKED_FIELDS.items() if self.has_value_changed(field)]
		if not changed:
			return

		if not frappe.db.exists("Invoice", {"team": self.team}):
			return

		frappe.throw(
			_("This team has already been invoiced, so its billing {0} can no longer be changed.").format(
				_(" and ").join(changed)
			),
			frappe.ValidationError,
		)

	def validate_gstin(self):
		if not self.gstin:
			return
		self.gstin = self.gstin.strip().upper()
		if not validate_gstin(self.gstin):
			frappe.throw(
				_("'{0}' is not a valid GSTIN (expected 15 characters, e.g. 27AAPFU0939F1ZV).").format(
					self.gstin
				),
				frappe.ValidationError,
			)

	def validate_india_state(self):
		"""For an Indian billing address, the state must come from the GST state
		list, and a GSTIN's first two digits must be that state's code."""
		if (self.country or "").strip() != INDIA:
			return

		state = (self.state or "").strip()
		if state and state not in GST_STATE_CODES:
			frappe.throw(
				_("'{0}' is not a recognised Indian state — pick one from the list.").format(state),
				frappe.ValidationError,
			)

		if self.gstin:
			if not state:
				frappe.throw(
					_("Select the GST registration state for an Indian GSTIN."), frappe.ValidationError
				)
			expected = GST_STATE_CODES[state]
			if self.gstin[:2] != expected:
				frappe.throw(
					_(
						"GSTIN state code '{0}' does not match {1} (code {2}). The first two digits of a GSTIN are the registration state's code."
					).format(self.gstin[:2], state, expected),
					frappe.ValidationError,
				)
