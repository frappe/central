# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Event — the append-only, derived transition/money stream (ADR 0016).

Written only by `billing.states` (`transition` and `record_event`). It is a projection: no pricing,
invoicing, settlement, dunning or entitlement code may read it, so dropping the table
would not change a single invoice total. Its readers are engineers debugging, the
admin UI, and the reports.
"""

import frappe
from frappe.model.document import Document

_FLOW_BY_DOCTYPE = {
	"Billing Profile": "Billing Profile",
	"Tax Profile": "Billing Profile",
	"Subscription": "Subscription",
	"Invoice": "Invoice",
	"Billing Run": "Billing Run",
	"Payment Attempt": "Payment",
	"Refund": "Payment",
	"Top-up Order": "Payment",
	"Payment Method": "Payment Method",
	"Credit Ledger Entry": "Credit",
	"Credit Wallet": "Credit",
	"Webhook Event": "Webhook",
}
_FAILURE_WORDS = ("failed", "declined", "refused")


def flow_of(subject_doctype: str | None) -> str:
	return _FLOW_BY_DOCTYPE.get(subject_doctype, "Other")


def outcome_of(event_type: str | None, to_state: str | None) -> str:
	text = f"{event_type} {to_state}".lower()
	return "Failed" if any(word in text for word in _FAILURE_WORDS) else "Success"


class BillingEvent(Document):
	def before_insert(self):
		"""Name the flow and the outcome here, so every writer gets them the same way."""
		self.category = self.category or flow_of(self.subject_doctype)
		self.outcome = outcome_of(self.event_type, self.to_state)


def on_doctype_update() -> None:
	# The First Payment dashboard reads a subject's failures by kind on every load.
	frappe.db.add_index("Billing Event", ["subject_doctype", "event_type"])
	frappe.db.add_index("Billing Event", ["category", "outcome"])
