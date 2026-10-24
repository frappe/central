# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Card disputes (chargebacks) reported by the gateway's webhooks.

An opened dispute is noted on the invoice for a person to answer. A lost dispute
over the whole charge cancels the invoice: a credit note, the wallet part given
back, and no refund, because the gateway has already taken the money back. A lost
dispute over part of a charge gets a credit note for that part only. A lost dispute
on an invoice that is no longer Paid is put in front of an operator, because the
customer may have been refunded as well.
"""

import frappe

DISPUTE_EVENTS = (
	"charge.dispute.created",
	"charge.dispute.closed",
	"payment.dispute.created",
	"payment.dispute.won",
	"payment.dispute.lost",
	"payment.dispute.closed",
)


def is_dispute(event_type: str) -> bool:
	return event_type in DISPUTE_EVENTS


def apply_dispute(event, payload: dict) -> dict:
	"""Act on one dispute event. Returns what was done, for the Webhook Event."""
	from central.billing.gateways.registry import adapter_class

	adapter_key = frappe.db.get_value("Payment Gateway", event.gateway, "adapter_key")
	dispute = adapter_class(adapter_key).dispute_from_event(payload)
	attempt = _attempt_for(dispute and dispute["payment_id"])
	if not attempt:
		return {"handled": False, "reason": "no_matching_attempt"}
	event.payment_attempt = attempt.name
	invoice = frappe.get_doc("Invoice", attempt.invoice)

	if dispute["status"] == "open":
		_note(invoice, f"Card dispute {dispute['id']} opened for {dispute['amount']} ({dispute['reason']}).")
		return {"handled": True, "result": "noted"}
	if dispute["status"] != "lost":
		_note(invoice, f"Card dispute {dispute['id']} closed: {dispute['status']}.")
		return {"handled": True, "result": dispute["status"]}
	if invoice.status != "Paid":
		_flag(
			invoice,
			f"Card dispute {dispute['id']} lost for {dispute['amount']} on a {invoice.status} invoice.",
		)
		return {"handled": True, "result": "flagged", "invoice_status": invoice.status}
	from central.billing.payments import corrections

	lost = {"id": dispute["id"], "payment_id": dispute["payment_id"]}
	if dispute["amount"] + 0.005 < frappe.utils.flt(attempt.amount):
		# Part of the charge: a credit note for that part, and nothing refunded.
		corrections.refund_part(
			invoice.name,
			dispute["amount"],
			f"Card dispute lost for part of the charge ({dispute['reason']})",
			dispute=lost,
		)
		return {"handled": True, "result": "partly_refunded", "invoice": invoice.name}

	corrections.cancel_and_refund(invoice.name, f"Card dispute lost ({dispute['reason']})", dispute=lost)
	return {"handled": True, "result": "cancelled", "invoice": invoice.name}


def _attempt_for(payment_id: str | None):
	if not payment_id:
		return None
	name = frappe.db.get_value("Payment Attempt", {"gateway_transaction_id": payment_id}, "name")
	return frappe.get_doc("Payment Attempt", name) if name else None


def _note(invoice, text: str) -> None:
	invoice.add_comment("Info", text)


def _flag(invoice, text: str) -> None:
	"""Money the gateway took back that Central has no correction for: an operator decides."""
	_note(invoice, text)
	frappe.log_error(title=f"Dispute needs review on {invoice.name}", message=text)
