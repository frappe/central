# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment Attempt — one charge against an invoice.

The idempotency key is derived from the invoice and the retry number, so the same
charge always produces the same key and the gateway can dedupe it (ADR 0017).
"""

import hashlib
from datetime import datetime

import frappe
from frappe.model.document import Document
from pypika.terms import Criterion


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


def gateway_hold_active(attempt, now: datetime | None = None) -> Criterion:
	"""Query condition on the Payment Attempt table: the gateway holds the debit at `now`.

	A held debit waits for its gateway on purpose (a Razorpay debit in progress, an
	Indian card's pre-debit notice), so it is not stuck until its hold ends."""
	now = now or frappe.utils.now_datetime()
	return attempt.gateway_hold_until.isnotnull() & (attempt.gateway_hold_until > now)


class PaymentAttempt(Document):
	def validate(self):
		if not self.idempotency_key:
			self.idempotency_key = idempotency_key(self.invoice, self.retry_number)
		if not self.initiated_at:
			self.initiated_at = frappe.utils.now_datetime()

	def is_held_by_gateway(self, now: datetime | None = None) -> bool:
		"""The gateway holds this debit at `now`. The same condition as `gateway_hold_active`."""
		now = frappe.utils.get_datetime(now or frappe.utils.now_datetime())
		return bool(self.gateway_hold_until) and now < frappe.utils.get_datetime(self.gateway_hold_until)


def on_doctype_update() -> None:
	# The billing run, its dashboards and the money reports filter on these.
	frappe.db.add_index("Payment Attempt", ["invoice"])
	frappe.db.add_index("Payment Attempt", ["team"])
	frappe.db.add_index("Payment Attempt", ["gateway_order_id"])
	frappe.db.add_index("Payment Attempt", ["status", "creation"])
