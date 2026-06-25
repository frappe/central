# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Append-only subscription history.

A change row is a historical fact: once written it is never edited. The
controller forbids any re-save after creation, so the audit trail cannot be
rewritten.
"""

import frappe
from frappe.model.document import Document


class SubscriptionChange(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		change_type: DF.Literal["Created", "Plan Changed", "Payment Method Changed", "Past Due", "Suspended", "Reactivated", "Cancelled"]
		changed_by: DF.Data | None
		currency: DF.Link | None
		effective_at: DF.Datetime | None
		locked_rate: DF.Currency
		new_value: DF.Data | None
		old_value: DF.Data | None
		subscription: DF.Link
		team: DF.Link | None
	# end: auto-generated types

	def validate(self):
		if not self.is_new():
			frappe.throw(
				"Subscription Change is append-only; history cannot be edited.",
				frappe.ValidationError,
			)
