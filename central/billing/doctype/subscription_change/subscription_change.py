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
	def validate(self):
		if not self.is_new():
			frappe.throw(
				"Subscription Change is append-only; history cannot be edited.",
				frappe.ValidationError,
			)
