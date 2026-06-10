# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaymentMethod(Document):
	def validate(self):
		self._reject_duplicate_card()

	def _reject_duplicate_card(self):
		"""A team can't register the same card twice. Using one card as both the
		primary and a backup gives no real fallback, so it is disallowed."""
		if not self.gateway_method_id or self.status == "cancelled":
			return
		dup = frappe.get_all(
			"Payment Method",
			filters={
				"team": self.team,
				"gateway_method_id": self.gateway_method_id,
				"status": ["!=", "cancelled"],
				"name": ["!=", self.name or ""],
			},
			limit=1,
		)
		if dup:
			frappe.throw(
				"This card is already on file for the team — the same card can't be "
				"used as both the primary and a backup method.",
				frappe.ValidationError,
			)
