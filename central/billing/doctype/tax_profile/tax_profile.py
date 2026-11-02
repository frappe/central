# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TaxProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		output_tax_rate: DF.Float
		output_tax_type: DF.Literal["None", "GST", "VAT"]
		tds_applicable: DF.Check
		tds_rate: DF.Float
		team: DF.Link
		zero_rated: DF.Check
		zero_rating_reason: DF.Literal["", "SEZ", "Overseas"]
	# end: auto-generated types

	def validate(self):
		# An auditor will ask why tax is 0 — a zero-rated profile must say why.
		if self.zero_rated and not self.zero_rating_reason:
			frappe.throw(
				_("A zero-rated tax profile needs a compliance reason (sez_lut / export)."),
				frappe.ValidationError,
			)
