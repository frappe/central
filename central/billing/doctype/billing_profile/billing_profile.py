# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

from central.billing.india_gst import GST_STATE_CODES, INDIA

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_gstin(gstin: str) -> bool:
	return bool(GSTIN_RE.match((gstin or "").strip().upper()))


class BillingProfile(Document):
	def validate(self):
		self.validate_gstin()
		self.validate_india_state()

	def validate_gstin(self):
		if not self.gstin:
			return
		self.gstin = self.gstin.strip().upper()
		if not validate_gstin(self.gstin):
			frappe.throw(
				f"'{self.gstin}' is not a valid GSTIN (expected 15 characters, e.g. 27AAPFU0939F1ZV).",
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
				f"'{state}' is not a recognised Indian state — pick one from the list.",
				frappe.ValidationError,
			)

		if self.gstin:
			if not state:
				frappe.throw("Select the GST registration state for an Indian GSTIN.", frappe.ValidationError)
			expected = GST_STATE_CODES[state]
			if self.gstin[:2] != expected:
				frappe.throw(
					f"GSTIN state code '{self.gstin[:2]}' does not match {state} (code {expected}). "
					"The first two digits of a GSTIN are the registration state's code.",
					frappe.ValidationError,
				)
