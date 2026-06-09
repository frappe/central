# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe.model.document import Document

# GSTIN: 2-digit state + 10-char PAN + entity digit + 'Z' + checksum char.
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_gstin(gstin: str) -> bool:
	return bool(GSTIN_RE.match((gstin or "").strip().upper()))


class BillingProfile(Document):
	def validate(self):
		if self.gstin:
			self.gstin = self.gstin.strip().upper()
			if not validate_gstin(self.gstin):
				frappe.throw(
					f"'{self.gstin}' is not a valid GSTIN (expected 15 characters, e.g. 27AAPFU0939F1ZV).",
					frappe.ValidationError,
				)
