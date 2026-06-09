# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TaxProfile(Document):
	def validate(self):
		# An auditor will ask why tax is 0 — a zero-rated profile must say why.
		if self.zero_rated and not self.zero_rating_reason:
			frappe.throw(
				"A zero-rated tax profile needs a compliance reason (sez_lut / export).",
				frappe.ValidationError,
			)
