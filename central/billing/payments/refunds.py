# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Post-payment corrections — refunds (issue #15).

Two destinations, two mechanics:

  - **Full dispute -> source.** Refund the captured amount through the gateway
    (`adapter.refund`, symmetric across Stripe/Razorpay). The invoice **stays
    Paid** with a linked Refund — there is no "Refunded" state, which preserves
    GST immutability; the statutory credit note is issued in ERPNext (#17).
  - **Partial overcharge -> wallet.** Add the difference to the customer's
    wallet as a credit ledger entry, applied on the next invoice. No gateway
    round-trip — it is a credit, not a chargeback.

Pre-payment corrections (Draft/Open) are NOT refunds: cancel + reissue, so an
issued line item is never mutated (see billing.reissue_invoice).
"""

import frappe

from central.billing.revenue import credits
from central.billing.states import transition


def _adapter(gateway: str):
	from central.billing.gateways.registry import get_adapter

	return get_adapter(frappe.get_doc("Payment Gateway", gateway))


def issue_refund(payment_attempt: str, amount=None, destination: str = "Source", reason: str | None = None):
	"""Refund (part of) a captured Payment Attempt to source or to the wallet.

	`amount` defaults to the full captured amount (a full dispute). The invoice
	is never moved off Paid.
	"""
	attempt = frappe.get_doc("Payment Attempt", payment_attempt)
	if attempt.status not in ("Captured", "Refunded"):
		frappe.throw(
			f"Only a captured charge can be refunded (attempt is {attempt.status}).",
			frappe.ValidationError,
		)

	amount = frappe.utils.flt(amount) if amount else frappe.utils.flt(attempt.amount)
	if amount <= 0 or amount > frappe.utils.flt(attempt.amount):
		frappe.throw("Refund amount must be > 0 and <= the captured amount.", frappe.ValidationError)

	refund = frappe.get_doc(
		{
			"doctype": "Refund",
			"payment_attempt": payment_attempt,
			"invoice": attempt.invoice,
			"team": attempt.team,
			"amount": amount,
			"currency": attempt.currency,
			"destination": destination,
			"reason": reason,
			"status": "Initiated",
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)

	if destination == "Wallet":
		_to_wallet(refund, attempt)
	else:
		_to_source(refund, attempt, reason)

	return refund


def full_dispute(payment_attempt: str, reason: str | None = None):
	"""Refund the whole charge to source; the invoice stays Paid + linked Refund."""
	return issue_refund(payment_attempt, amount=None, destination="Source", reason=reason)


def partial_overcharge(payment_attempt: str, amount, reason: str | None = None, to_source: bool = False):
	"""Correct a partial overcharge: to the wallet by default (active customers),
	to source for churning customers (`to_source=True`)."""
	return issue_refund(
		payment_attempt, amount=amount, destination="Source" if to_source else "Wallet", reason=reason
	)


def _to_wallet(refund, attempt):
	"""Book the overcharge as a wallet credit, applied next cycle."""
	credits.refund_to_wallet(
		attempt.team,
		refund.amount,
		currency=attempt.currency or "INR",
		reference_type="Refund",
		reference_name=refund.name,
		note=refund.reason or f"Overcharge refund for {attempt.invoice}",
	)
	transition(
		refund, "Completed", actor=frappe.session.user, correlation=attempt.invoice, amount=refund.amount
	)
	refund.completed_at = frappe.utils.now_datetime()
	refund.save(ignore_permissions=True)
	return refund


def _to_source(refund, attempt, reason):
	"""Refund to the gateway via the adapter (symmetric across gateways)."""
	result = _adapter(attempt.gateway).refund(attempt, refund.amount, reason or "")
	refund.gateway_refund_id = result.gateway_refund_id
	transition(
		refund,
		"Completed" if result.success else "Failed",
		actor=frappe.session.user,
		correlation=attempt.invoice,
		amount=refund.amount,
	)
	if result.success:
		refund.completed_at = frappe.utils.now_datetime()
		# A full refund marks the attempt refunded (the invoice still stays Paid).
		if frappe.utils.flt(refund.amount) >= frappe.utils.flt(attempt.amount):
			transition(
				attempt,
				"Refunded",
				actor=frappe.session.user,
				correlation=attempt.invoice,
				amount=refund.amount,
			)
			attempt.save(ignore_permissions=True)
	refund.save(ignore_permissions=True)
	return refund
