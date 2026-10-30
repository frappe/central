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

		internal_reason: DF.SmallText | None
		is_internal: DF.Check
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
		if self.is_internal and not (self.internal_reason or "").strip():
			frappe.throw(_("Write why this team is internal."), frappe.ValidationError)

	def on_update(self):
		"""Log who marked or cleared the team as internal, and why."""
		before = self.get_doc_before_save()
		if bool(self.is_internal) == bool(before and before.is_internal):
			return

		from central.billing.revenue.invoicing.lifecycle import waive_for_internal_team
		from central.billing.states import record_event

		record_event(
			self,
			"Internal Team Marked" if self.is_internal else "Internal Team Cleared",
			reason=self.internal_reason,
		)
		if self.is_internal:
			waive_for_internal_team(self.team)
