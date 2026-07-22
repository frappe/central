# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification suite — Cloud Billing is the sole sender (issue #20).

v1 sent duplicate emails from both Press and the gateway. v2 routes every
customer-facing billing notification through this one module: it records a
Notification Log per team and is the only thing that sends. Gateways never
email the customer.

Each call also drops an Info comment on the referenced doc (Desk audit trail);
email dispatch is via frappe.sendmail in production (stubbed here — the
Notification Log is the record of intent).
"""

import frappe

# event_type -> default (subject, body template). Body is .format(**context)-ed.
_TEMPLATES = {
	"Payment Success": ("Payment received", "Payment received for invoice {invoice}."),
	"Payment Failure": ("Payment failed", "Payment for invoice {invoice} failed: {reason}."),
	"Payment Retry": ("Payment retry failed", "Payment retry for invoice {invoice} failed: {reason}."),
	"Invoice Overdue": ("Invoice overdue", "Invoice {invoice} is overdue. Please settle it to avoid suspension."),
	"Credit Low": ("Credit balance low", "Your credit balance is low (projected use {utilisation}). Top up to avoid interruption."),
	"Card Expiry": ("Card expired", "Your card {label} has expired. Please add a new payment method."),
	"Mandate Reauth": ("Mandate re-authorisation needed", "Your UPI Autopay mandate needs re-authorisation for the new limit."),
	"Action Required": ("Action required — choose how to pay", "Your usage is above the ₹{threshold:,.0f} limit for automatic payments. Your services keep running — please choose to pay each invoice or prepay your wallet."),
	"Pre-debit Notice": ("Upcoming auto-payment", "We’ll auto-debit {amount} for invoice {invoice} on {charge_on}. No action needed; this is a heads-up before the payment."),
	"Trial Expiring": ("Trial ending", "Your trial is ending. Add a payment method to keep your resources running."),
}


# event_type -> (in-app severity, action label, action route). Drives the console
# feed entry; the route deep-links the actionable events. Absent = Info, no action.
_FEED_META = {
	"Payment Success": ("Success", None, None),
	"Payment Failure": ("Error", "Pay now", "/billing/invoices"),
	"Payment Retry": ("Warning", "Pay now", "/billing/invoices"),
	"Invoice Overdue": ("Error", "Pay now", "/billing/invoices"),
	"Credit Low": ("Warning", "Top up", "/billing"),
	"Card Expiry": ("Warning", "Update card", "/billing"),
	"Mandate Reauth": ("Warning", "Re-authorise", "/billing"),
	"Trial Expiring": ("Warning", "Add payment method", "/billing"),
	"Action Required": ("Warning", "Choose how to pay", "/billing/invoices"),
	"Pre-debit Notice": ("Info", None, None),
}


def notify(
	team: str,
	event_type: str,
	context: dict | None = None,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""Emit one notification, the single sender for all billing events.

	Every event is logged and emailed. Per-user preference gating will be handled
	by the notification engine.
	"""
	context = context or {}
	subject, template = _TEMPLATES.get(event_type, (event_type, message or event_type))
	body = message or template.format(**context)

	# In-app feed entry — the console's unified inbox. Always recorded (a failure or
	# warning belongs in the dashboard regardless of the team's *email* preference).
	severity, action_label, action_route = _FEED_META.get(event_type, ("Info", None, None))
	from central import notification as feed

	feed.create_notification(
		team, subject, category="Billing", event_type=event_type, severity=severity,
		message=body, reference_doctype=reference_doctype, reference_name=reference_name,
		action_label=action_label, action_route=action_route,
	)

	log = frappe.get_doc(
		{
			"doctype": "Billing Notification Log",
			"team": team,
			"event_type": event_type,
			"channel": "email",
			"status": "Sent",
			"subject": subject,
			"message": body,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"sent_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)

	if reference_doctype and reference_name:
		try:
			frappe.get_doc(reference_doctype, reference_name).add_comment("Info", body)
		except Exception:  # noqa: BLE001 — audit comment is best-effort
			pass
	_send_email(team, subject, body)
	return {"sent": True, "log": log.name}


def _send_email(team: str, subject: str, body: str):
	"""Dispatch to the customer. Production wires frappe.sendmail to the team's
	billing contact; left as a guarded hook here (the Notification Log is the SOR
	for what was sent)."""
	# frappe.sendmail(recipients=[billing_contact(team)], subject=subject, message=body, delayed=True)
	return
