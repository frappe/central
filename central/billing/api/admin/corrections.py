# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin corrections to an invoice: cancel it, or cancel it and refund the money."""

import frappe
from frappe import _

from central.billing import authz


@frappe.whitelist(methods=["POST"])
def cancel_invoice(invoice: str, reason: str) -> dict:
	"""Cancel an unpaid invoice. What it drew from the wallet goes back."""
	authz.require_operator()
	from central.billing.revenue.invoicing.lifecycle import cancel_invoice as cancel

	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the cancellation."), frappe.ValidationError)
	cancel(invoice, reason=reason.strip())
	return {"invoice": invoice, "status": frappe.db.get_value("Invoice", invoice, "status")}


@frappe.whitelist(methods=["POST"])
def cancel_and_refund(invoice: str, reason: str) -> dict:
	"""Cancel a paid invoice: a credit note, and each part of the payment given back."""
	authz.require_operator()
	from central.billing.payments.corrections import cancel_and_refund as cancel

	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the cancellation."), frappe.ValidationError)
	return cancel(invoice, reason.strip())


@frappe.whitelist(methods=["POST"])
def retry_failed_refunds(invoice: str) -> dict:
	"""Try again the card or UPI refunds a gateway refused for this invoice."""
	authz.require_operator()
	from central.billing.payments.corrections import retry_failed_refunds as retry

	return {"invoice": invoice, "retried": retry(invoice)}


@frappe.whitelist(methods=["POST"])
def refund_part(invoice: str, amount: float, destination: str, reason: str) -> dict:
	"""Give back part of a paid invoice, to the wallet or to the card or UPI that paid it."""
	authz.require_operator()
	from central.billing.payments.corrections import refund_part as refund

	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the refund."), frappe.ValidationError)
	return refund(invoice, amount, reason.strip(), destination=destination)


@frappe.whitelist(methods=["POST"])
def mark_usage_credited(correction: str, reason: str) -> dict:
	"""Record that the credit note a lower usage value asked for was issued."""
	authz.require_operator()
	from central.billing.revenue.usage_corrections import mark_credited

	if not (reason or "").strip():
		frappe.throw(
			_("Name the credit note or refund that settled this correction."), frappe.ValidationError
		)
	mark_credited(correction, reason.strip())
	return {
		"correction": correction,
		"status": frappe.db.get_value("Usage Month Correction", correction, "status"),
	}


@frappe.whitelist(methods=["POST"])
def mark_usage_billed_by_hand(correction: str, reason: str) -> dict:
	"""Record that what a reissued usage correction added was billed by hand."""
	# Platform staff only: it closes a readiness M7 row, so a team must never clear its own debt.
	authz.require_operator()
	from central.billing.revenue.usage_corrections import mark_billed_by_hand

	if not (reason or "").strip():
		frappe.throw(_("Name the invoice that billed this correction by hand."), frappe.ValidationError)
	mark_billed_by_hand(correction, reason.strip())
	return {
		"correction": correction,
		"status": frappe.db.get_value("Usage Month Correction", correction, "status"),
	}
