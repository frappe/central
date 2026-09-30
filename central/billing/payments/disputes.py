# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Card disputes (chargebacks) reported by the gateway's webhooks.

An opened dispute is noted on the invoice for a person to answer. A lost dispute
over the whole charge cancels the invoice: a credit note, the wallet part given
back, and no refund, because the gateway has already taken the money back. A lost
dispute over part of a charge is left to a person, since it needs a credit note
for that part only.
"""

import frappe

DISPUTE_EVENTS = ("charge.dispute.created", "charge.dispute.closed")


def is_dispute(event_type: str) -> bool:
	return event_type in DISPUTE_EVENTS


def apply_dispute(event, payload: dict) -> dict:
	"""Act on one dispute event. Returns what was done, for the Webhook Event."""
	dispute = (payload.get("data") or {}).get("object") or {}
	attempt = _attempt_for(dispute.get("payment_intent"))
	if not attempt:
		return {"handled": False, "reason": "no_matching_attempt"}
	invoice = frappe.get_doc("Invoice", attempt.invoice)
	amount = frappe.utils.flt(dispute.get("amount")) / 100
	reason = dispute.get("reason") or "unknown"

	if event.event_type == "charge.dispute.created":
		_note(invoice, f"Card dispute {dispute.get('id')} opened for {amount} ({reason}).")
		return {"handled": True, "result": "noted"}
	if dispute.get("status") != "lost":
		_note(invoice, f"Card dispute {dispute.get('id')} closed: {dispute.get('status')}.")
		return {"handled": True, "result": dispute.get("status")}
	if invoice.status != "Paid":
		return {"handled": True, "result": "already_settled", "invoice_status": invoice.status}
	if amount + 0.005 < frappe.utils.flt(attempt.amount):
		_note(invoice, f"Card dispute {dispute.get('id')} lost for part of the charge: {amount}.")
		frappe.log_error(
			title=f"Partial dispute lost: {invoice.name}",
			message=f"Dispute {dispute.get('id')} took back {amount} of {attempt.amount}. "
			"Issue a credit note for that part by hand.",
		)
		return {"handled": True, "result": "partial_for_a_person"}

	from central.billing.payments import corrections

	corrections.cancel_and_refund(
		invoice.name,
		f"Card dispute lost ({reason})",
		dispute={"id": dispute.get("id"), "payment_intent": dispute.get("payment_intent")},
	)
	return {"handled": True, "result": "cancelled", "invoice": invoice.name}


def _attempt_for(payment_intent: str | None):
	if not payment_intent:
		return None
	name = frappe.db.get_value("Payment Attempt", {"gateway_transaction_id": payment_intent}, "name")
	return frappe.get_doc("Payment Attempt", name) if name else None


def _note(invoice, text: str) -> None:
	invoice.add_comment("Info", text)
