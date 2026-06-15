# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification suite — Cloud Billing is the sole sender (issue #20).

v1 sent duplicate emails from both Press and the gateway. v2 routes every
customer-facing billing notification through this one module: it records a
Notification Log per team, honours the team's preferences, and is the only thing
that sends. Gateways never email the customer.

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


def _preference_enabled(team: str, event_type: str) -> bool:
	"""A team's opt-out for an event; absent preference doc = all enabled."""
	if not frappe.db.exists("Notification Preference", team):
		return True
	fieldname = "notify_" + event_type.lower().replace(" ", "_")
	value = frappe.db.get_value("Notification Preference", team, fieldname)
	return value is None or bool(value)


def notify(
	team: str,
	event_type: str,
	context: dict | None = None,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""Emit one notification, the single sender for all billing events.

	Suppressed (by preference) events are still logged — as `suppressed` — so the
	suppression itself is auditable, but nothing is sent.
	"""
	context = context or {}
	subject, template = _TEMPLATES.get(event_type, (event_type, message or event_type))
	body = message or template.format(**context)

	enabled = _preference_enabled(team, event_type)
	log = frappe.get_doc(
		{
			"doctype": "Billing Notification Log",
			"team": team,
			"event_type": event_type,
			"channel": "email",
			"status": "Sent" if enabled else "Suppressed",
			"subject": subject,
			"message": body,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"sent_at": frappe.utils.now_datetime() if enabled else None,
		}
	).insert(ignore_permissions=True)

	if not enabled:
		return {"sent": False, "reason": "suppressed", "log": log.name}

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
