# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.india_gst import GST_STATE_CODES, INDIA

# Once a team has been invoiced, these are frozen: invoices are denominated in the
# currency and taxed by the country in force when they were issued, so changing
# either would desync documents already sent to the customer.
_INVOICE_LOCKED_FIELDS = {"country": "country", "currency": "currency"}

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_gstin(gstin: str) -> bool:
	return bool(GSTIN_RE.match((gstin or "").strip().upper()))


class BillingProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		address_line1: DF.Data | None
		address_line2: DF.Data | None
		city: DF.Data | None
		collection_action_reason: DF.Data | None
		collection_mode: DF.Literal["Auto Charge", "Manual Checkout", "Prepaid", "Action Required"]
		country: DF.Link | None
		currency: DF.Link | None
		email: DF.Data | None
		gst_status: DF.Literal["", "Active", "Invalid", "Suspended", "Cancelled"]
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
		self.validate_gstin()
		self.validate_india_state()
		self.lock_country_and_currency_after_invoicing()

	def on_update(self):
		self.release_held_invoices()
		self.enqueue_profile_sync()

	def enqueue_profile_sync(self):		
		if not self.profile_id:
			method = 'central.billing.ingester.customer.create_customer_profile'
		else:
			method = 'central.billing.ingester.customer.update_customer_profile'

		frappe.enqueue(
			method,
			queue="short",
			billing_profile=self,
			enqueue_after_commit=True,
		)

	def release_held_invoices(self):
		"""Settle anything held back for these details once they are on file.

		On the doctype rather than one endpoint: the profile is completed from the
		dashboard, from the bench's own billing tab and from Desk, and an invoice
		stuck for a missing legal name must not depend on which door it came through.
		"""
		from central.billing.api.dashboard._shared import _profile_complete
		from central.billing.revenue.invoicing.run import release_held_drafts

		if _profile_complete(self.team):
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
