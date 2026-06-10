# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment Attempt — one charge against an invoice.

The idempotency key IS the attempt's own (random) name, so a retry of the same
attempt reuses the key and the gateway dedupes — a network timeout can be
retried without risk of a double charge.
"""

import frappe
from frappe.model.document import Document


class PaymentAttempt(Document):
	def validate(self):
		if not self.idempotency_key:
			self.idempotency_key = self.name
		if not self.initiated_at:
			self.initiated_at = frappe.utils.now_datetime()
