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

# What an operator changes to move a team on the trust ladder by hand.
_TIER_FIELDS = ("trust_tier_level", "override_max_spend")

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
# A phone the gateways accept: 8 to 15 digits with an optional leading +. An Indian
# mobile is 10 digits that start with 6 to 9, optionally after +91 or 91.
PHONE_RE = re.compile(r"^\+?[0-9]{8,15}$")
INDIAN_MOBILE_RE = re.compile(r"^(?:\+?91)?[6-9][0-9]{9}$")
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

	return get_missing_fields_of(frappe.get_doc("Billing Profile", team))


def get_missing_fields_of(profile) -> list[str]:
	"""Missing required fields on an already-loaded profile row. No row means all."""
	if profile is None:
		return list(REQUIRED_FIELDS)
	return [field for field in REQUIRED_FIELDS if not str(profile.get(field) or "").strip()]


def get_field_labels(fields: list[str]) -> list[str]:
	return [FIELD_LABELS.get(field, field) for field in fields]


def get_missing_field_labels(team: str) -> list[str]:
	return get_field_labels(get_missing_fields(team))


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
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address_id: DF.Data | None
		address_line1: DF.Data | None
		address_line2: DF.Data | None
		city: DF.Data | None
		collection_action_reason: DF.Data | None
		collection_mode: DF.Literal["Auto Charge", "Manual Checkout", "Prepaid", "Action Required"]
		contact_id: DF.Data | None
		country: DF.Link | None
		currency: DF.Link | None
		email: DF.Data | None
		gst_category: DF.Data | None
		gst_status: DF.Literal["", "Active", "Inactive", "Suspended", "Cancelled", "Invalid"]
		gst_status_checked_at: DF.Datetime | None
		gst_status_retry_after: DF.Datetime | None
		gstin: DF.Data | None
		legal_name: DF.Data | None
		manual_override: DF.Check
		min_balance: DF.Currency
		override_max_spend: DF.Currency
		phone: DF.Data | None
		pincode: DF.Data | None
		profile_id: DF.Data | None
		promoted_at: DF.Datetime | None
		promotion_basis: DF.SmallText | None
		spend_alert_threshold: DF.Currency
		state: DF.Autocomplete | None
		team: DF.Link
		team_owner: DF.ReadOnly | None
		trust_tier: DF.Data | None
		trust_tier_level: DF.Link | None
	# end: auto-generated types

	def validate(self):
		self.validate_phone()
		self.validate_gstin()
		self.validate_india_state()
		self.lock_country_and_currency_after_invoicing()
		self.validate_currency_matches_country()
		self.keep_mandates_in_the_billing_currency()
		self.pin_tier_set_by_hand()
		self.sync_tier_fields()

	def on_update(self):
		# Before held invoices are released: releasing re-taxes them from the Tax Profile.
		self.apply_output_tax_on_country_change()
		self.release_held_invoices()
		self.refresh_gst_status_on_change()
		self.enqueue_profile_sync()
		self.apply_tier_change()

	def validate_currency_matches_country(self):
		"""India is billed only in INR, and only India is billed in INR."""
		if not self.country or not self.currency:
			return
		if (self.country.strip() == INDIA) == (self.currency == "INR"):
			return
		frappe.throw(
			_("A team in India is billed in INR.")
			if self.country.strip() == INDIA
			else _(
				"Only a team in India is billed in INR. Contact support to move a team billed in INR abroad."
			),
			frappe.ValidationError,
		)

	def keep_mandates_in_the_billing_currency(self):
		"""Refuse a currency change that would strand a payment method set up in the old one."""
		if self.is_new() or not self.has_value_changed("currency"):
			return
		stranded = frappe.get_all(
			"Payment Method",
			filters={
				"team": self.team,
				"status": ["!=", "Cancelled"],
				"mandate_currency": ["not in", ("", self.currency)],
			},
			pluck="display_label",
		)
		if stranded:
			frappe.throw(
				_("Remove the payment methods set up in the old currency before changing it: {0}.").format(
					", ".join(label or _("unnamed method") for label in stranded)
				),
				frappe.ValidationError,
			)

	def pin_tier_set_by_hand(self):
		"""Pin a tier or cap an operator sets, and require the reason for it."""
		if self.is_new() or self.flags.tier_set_by_system:
			return
		if not any(self.has_value_changed(field) for field in _TIER_FIELDS):
			return
		if not self.has_value_changed("promotion_basis") or not (self.promotion_basis or "").strip():
			frappe.throw(
				_("Write why the trust tier or spend cap changed in Tier Change Reason."),
				frappe.ValidationError,
			)
		self.manual_override = 1
		self.promoted_at = frappe.utils.now_datetime()

	def sync_tier_fields(self):
		"""Keep the tier name on the level, and drop a bespoke cap once the tier is unpinned."""
		self.trust_tier = (
			frappe.get_cached_value("Trust Tier Level", self.trust_tier_level, "tier")
			if self.trust_tier_level
			else None
		)
		if not self.manual_override:
			self.override_max_spend = 0

	def apply_tier_change(self):
		"""Re-check mandate ceilings against the new cap and log who moved the tier."""
		before = self.get_doc_before_save()
		if not before or not any(
			self.has_value_changed(field) for field in (*_TIER_FIELDS, "manual_override")
		):
			return

		from central.billing.payments import mandates
		from central.billing.states import record_event

		mandates.reconcile_mandates_to_cap(self.team)
		record_event(
			self,
			"Trust Tier Changed",
			from_state=before.trust_tier_level,
			to_state=self.trust_tier_level,
			reason=self.promotion_basis,
			amount=self.override_max_spend,
		)

	def apply_output_tax_on_country_change(self):
		"""The output tax follows the country, so a corrected signup country is taxed right."""
		if not (self.has_value_changed("country") or self.has_value_changed("currency")):
			return
		if not frappe.db.exists("Tax Profile", self.team):
			return  # created with the right values when the profile is provisioned
		from central.billing.payments.provisioning import apply_output_tax_for_country

		apply_output_tax_for_country(self.team)

	def refresh_gst_status_on_change(self):
		"""A new GSTIN starts with no status and is looked up in the background."""
		from central.billing.revenue import gst_status

		if self.has_value_changed("gstin"):
			gst_status.forget(self)

	def enqueue_profile_sync(self):
		from central.billing.ingester.customer import enqueue_sync

		enqueue_sync(self)

	def release_held_invoices(self):
		"""Settle anything held back for these details once they are on file.

		On the doctype rather than one endpoint: the profile is completed from the
		dashboard, from the bench's own billing tab and from Desk, and an invoice
		stuck for a missing legal name must not depend on which door it came through.
		"""
		from central.billing.revenue.invoicing.run import release_held_drafts

		if is_complete(self.team):
			release_held_drafts(self.team)

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

	def validate_phone(self):
		"""Razorpay refuses a mandate debit without a valid contact, so a phone it would
		refuse is caught here, where the customer can correct it. Only a phone being set is
		checked, so a stored one never blocks the system's own saves of the profile."""
		if not self.phone or not (self.is_new() or self.has_value_changed("phone")):
			return
		self.phone = re.sub(r"[\s()-]", "", self.phone)
		is_indian = (self.country or "").strip() == INDIA
		if (INDIAN_MOBILE_RE if is_indian else PHONE_RE).match(self.phone):
			return
		frappe.throw(
			_("Enter a 10-digit mobile number.")
			if is_indian
			else _("Enter a phone number of 8 to 15 digits, with the country code."),
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
