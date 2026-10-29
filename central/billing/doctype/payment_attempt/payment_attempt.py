# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment Attempt — one charge against an invoice.

The idempotency key is derived from the invoice and the retry number, so the same
charge always produces the same key and the gateway can dedupe it (ADR 0017).
"""

import hashlib

import frappe
from frappe.model.document import Document


def idempotency_key(invoice: str, retry_number) -> str:
	"""The gateway's dedupe key for one charge: a hash of (site, invoice, retry number).

	It is worked out from the facts rather than being a random id, and that is what
	protects the customer's card. If a worker dies after the gateway took the money
	but before we saved the attempt, the row is gone and the retry recomputes the
	*same* key — so the gateway replays its original answer instead of charging
	again. A real retry (the previous attempt failed and was saved) has a higher
	retry number, so it gets a different key and is allowed to charge.
	"""
	# The site is part of it: sites that share one gateway account reuse invoice names.
	return hashlib.sha256(
		f"{frappe.local.site}:{invoice}:{frappe.utils.cint(retry_number)}".encode()
	).hexdigest()


class PaymentAttempt(Document):
	def validate(self):
		if not self.idempotency_key:
			self.idempotency_key = idempotency_key(self.invoice, self.retry_number)
		if not self.initiated_at:
			self.initiated_at = frappe.utils.now_datetime()


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Payment Attempt", ["invoice"])
	frappe.db.add_index("Payment Attempt", ["team"])
	frappe.db.add_index("Payment Attempt", ["gateway_order_id"])
	frappe.db.add_index("Payment Attempt", ["status", "creation"])
