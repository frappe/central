# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Refund(Document):
	def on_update(self) -> None:
		"""The team did not ask for a refund of a late capture, so it hears when the money is back."""
		if self.late_capture and self.status == "Completed" and self.has_value_changed("status"):
			from central.billing.payments.payment_notices import notify_payment_refunded

			notify_payment_refunded(self)


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Refund", ["invoice"])
	frappe.db.add_index("Refund", ["status", "created_at"])
	# Reconciliation rechecks recently completed refunds.
	frappe.db.add_index("Refund", ["status", "completed_at"])
