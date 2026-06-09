# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Append-only credit ledger entry.

The wallet is the ledger; the balance is the running sum, never a scalar on
Team (the v1 negative-balance bug). An entry is a booked liability movement and
is never edited or deleted in the normal course — the controller forbids any
re-save after creation. Corrections are new entries, not edits.
"""

import frappe
from frappe.model.document import Document


class CreditLedgerEntry(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(
				"Credit Ledger Entry is append-only; book a correcting entry instead of editing.",
				frappe.ValidationError,
			)
