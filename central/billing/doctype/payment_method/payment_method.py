# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PaymentMethod(Document):
	def validate(self):
		self._reject_duplicate_card()

	def _reject_duplicate_card(self):
		"""A team can't register the same card twice. Using one card as both the
		primary and a backup gives no real fallback, so it is disallowed."""
		if not self.gateway_method_id or self.status == "Cancelled":
			return
		dup = frappe.get_all(
			"Payment Method",
			filters={
				"team": self.team,
				"gateway_method_id": self.gateway_method_id,
				"status": ["!=", "Cancelled"],
				"name": ["!=", self.name or ""],
			},
			limit=1,
		)
		if dup:
			frappe.throw(
				_(
					"This card is already on file for the team — the same card can't be "
					"used as both the primary and a backup method."
				),
				frappe.ValidationError,
			)

	def record_failure(
		self, failure_code: str | None, failure_reason: str | None = None, decline_code: str | None = None
	) -> None:
		"""Keep the gateway's reason for the latest failed setup or check of this method."""
		self.failed_attempts = frappe.utils.cint(self.failed_attempts) + 1
		self.last_failed_at = frappe.utils.now_datetime()
		self.failure_code = failure_code
		self.decline_code = decline_code
		self.failure_reason = (failure_reason or "")[:140] or None


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Payment Method", ["team", "status"])
