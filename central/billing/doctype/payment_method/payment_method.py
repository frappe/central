# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.billing.payments import decline


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

	def record_failure(self, failure: dict) -> None:
		"""Keep the gateway's reason for the latest failed setup or check of this method."""
		self.failed_attempts = frappe.utils.cint(self.failed_attempts) + 1
		self.last_failed_at = frappe.utils.now_datetime()
		self.update(decline.failure_fields(failure))

	def get_confirmation(self) -> dict:
		"""What a confirm route answers. A failed method says why, in words for the customer."""
		result = {"payment_method": self.name, "status": self.status}
		if self.status == "Failed":
			result["message"] = decline.method_failure_message(
				self.failure_code, self.decline_code, self.method_type
			)
		return result


def held_method_filters() -> dict:
	"""The `or_filters` that keep the methods a team holds. An abandoned setup stays on
	record as Cancelled with no gateway id, so the setup funnel can count it, but it
	never held a card or a mandate."""
	return {"status": ["!=", "Cancelled"], "gateway_method_id": ["is", "set"]}


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Payment Method", ["team", "status"])
	# A failed hosted card setup webhook finds its card by this.
	frappe.db.add_index("Payment Method", ["setup_intent_id"])
