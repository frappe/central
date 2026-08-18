# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A saved question, not a saved answer.

The overrides here never touch Billing Settings. They change what a projection *reads*,
for the length of that projection — so asking what a 2/5/10 dunning ladder would do
costs nobody their real configuration.
"""

import frappe
from frappe.model.document import Document

# The fields that stand in for Billing Settings while a projection runs.
OVERRIDE_FIELDS = (
	"dunning_retry_days",
	"invoice_due_days",
	"suspend_after_days",
	"terminate_after_days",
	"promotional_credit_validity_days",
)


class BillingScenario(Document):
	def validate(self):
		self.months = max(1, min(frappe.utils.cint(self.months) or 1, 24))
		if self.outcome_mode != "Assumed":
			self.assume = None

	def rate_overrides_applied(self) -> list[dict]:
		"""The pretended prices, as the pricing seam wants them."""
		return [
			{
				"priced_doctype": row.priced_doctype,
				"priced_for": row.priced_for,
				"cluster": row.cluster,
				"currency": row.currency,
				"percent": row.percent,
				"rate": row.rate or None,
				"effective_from": row.effective_from,
			}
			for row in (self.rate_overrides or [])
		]

	def injected_events(self) -> list[dict]:
		"""The invented events, as plain rows the projection can reason about."""
		return [
			{
				"event_type": row.event_type,
				"on_date": row.on_date,
				"subscription": row.subscription,
				"plan": row.plan,
				"rate": row.rate,
				"amount": row.amount,
				"currency": row.currency,
				"attempt": row.attempt,
			}
			for row in (self.events or [])
		]

	def effective_from(self):
		"""The earliest date any pretended price takes effect."""
		dates = [r.effective_from for r in (self.rate_overrides or []) if r.effective_from]
		return min(dates) if dates else None

	def overrides(self) -> dict:
		"""Only the fields actually filled in — a blank one means "use what is live"."""
		return {field: self.get(field) for field in OVERRIDE_FIELDS if self.get(field) not in (None, "", 0)}
