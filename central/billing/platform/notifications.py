# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification suite — Cloud Billing is the sole sender (issue #20).

v1 sent duplicate emails from both Press and the gateway. v2 routes every
customer-facing billing notification through this one module: it records a
Notification Log per team and is the only thing that sends. Gateways never
email the customer.

Each call also drops an Info comment on the referenced doc (Desk audit trail);
email dispatch goes through the unified notification engine.
"""

import frappe

from central.notification import engine

# Billing event type defaults — used to self-bootstrap the registry rows
# when the fixture hasn't been loaded yet (e.g. in isolated test runs).
_BILLING_EVENT_TYPES = {
	"payment_success": (
		"Payment received",
		"Payment received for invoice {{ reference_name }}.",
		"Success",
		"billing:view",
		None,
		None,
	),
	"payment_failure": (
		"Payment failed",
		"Payment for invoice {{ reference_name }} failed: {{ message }}",
		"Error",
		"billing:view",
		"Pay now",
		"/billing/invoices",
	),
	"payment_retry": (
		"Payment retry failed",
		"Payment retry for invoice {{ reference_name }} failed: {{ message }}",
		"Warning",
		"billing:view",
		"Pay now",
		"/billing/invoices",
	),
	"invoice_overdue": (
		"Invoice overdue",
		"Invoice {{ reference_name }} is overdue. Please settle it to avoid suspension.",
		"Error",
		"billing:view",
		"Pay now",
		"/billing/invoices",
	),
	"credit_low": (
		"Credit balance low",
		"Your credit balance is low (projected use {{ message }}). Top up to avoid interruption.",
		"Warning",
		"billing:view",
		"Top up",
		"/billing",
	),
	"card_expiry": (
		"Card expired",
		"Your card has expired. Please add a new payment method.",
		"Warning",
		"billing:view",
		"Update card",
		"/billing",
	),
	"mandate_reauth": (
		"Mandate re-authorisation needed",
		"Your UPI Autopay mandate needs re-authorisation for the new limit.",
		"Warning",
		"billing:view",
		"Re-authorise",
		"/billing",
	),
	"trial_expiring": (
		"Trial ending",
		"Your trial is ending. Add a payment method to keep your resources running.",
		"Warning",
		"billing:view",
		"Add payment method",
		"/billing",
	),
	"action_required": (
		"Action required — choose how to pay",
		"Your usage is above the limit for automatic payments. Please choose to pay each invoice or prepay your wallet.",
		"Warning",
		"billing:view",
		"Choose how to pay",
		"/billing/invoices",
	),
	"pre_debit_notice": (
		"Upcoming auto-payment",
		"We'll auto-debit for your upcoming invoice. No action needed; this is a heads-up before the payment.",
		"Info",
		"billing:view",
		None,
		None,
	),
	"team_suspension": (
		"Team suspended",
		"Your team has been suspended due to billing issues.",
		"Error",
		"billing:view",
		None,
		None,
	),
}


def _ensure_event_type(slug: str):
	"""Create the Event Type row if it doesn't already exist."""
	spec = _BILLING_EVENT_TYPES.get(slug)
	if not spec:
		return
	title, body, severity, cap, label, route = spec
	engine.ensure_event_type(
		slug,
		category="Billing",
		severity=severity,
		required_cap=cap,
		in_app_title=title,
		in_app_body=body,
		action_label=label,
		action_route=route,
	)


def _render_log_body(slug: str, ref: str | None, msg: str | None) -> str:
	"""Render the billing log body from the Event Type's in_app_body template."""
	event = frappe.db.get_value(
		"Notification Event Type",
		slug,
		"in_app_body",
		as_dict=False,
	)
	if not event:
		return msg or slug
	ctx = {"reference_name": ref or "", "message": msg or ""}
	return frappe.render_template(event, ctx)


def notify(
	team: str,
	event_type: str,
	context: dict | None = None,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> dict:
	"""Emit one notification, the single sender for all billing events.

	Delegates to :func:`central.notification.engine.dispatch` for registry
	lookup, Jinja rendering, Team Notification creation, dedup, and email
	fan-out.  The ``Billing Notification Log`` is an independent audit record.
	"""
	src = dict(context or {})

	# Map billing callers' legacy context keys to the engine template variables.
	# billing callers:  context={"invoice": "INV-1", "reason": "card_declined"}
	# engine templates: {{ reference_name }}, {{ message }}
	ref = reference_name or src.pop("invoice", None)
	msg = message or src.pop("reason", None) or src.pop("utilisation", None)

	# The registry uses snake_case event_type names; billing callers use
	# Pascal Case (e.g. "Payment Success" → "payment_success").
	slug = event_type.lower().replace(" ", "_")
	_ensure_event_type(slug)

	result = engine.dispatch(
		team,
		slug,
		context=src,
		message=msg,
		reference_doctype=reference_doctype,
		reference_name=ref,
	)

	body = _render_log_body(slug, ref, msg)
	created = result.get("created", False)
	log = frappe.get_doc(
		{
			"doctype": "Billing Notification Log",
			"team": team,
			"event_type": event_type,
			"channel": "email",
			"status": "Sent",
			"subject": result.get("title") or event_type,
			"message": message or body,
			"reference_doctype": reference_doctype,
			"reference_name": ref,
			"sent_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)

	if reference_doctype and ref:
		try:
			frappe.get_doc(reference_doctype, ref).add_comment(
				"Info",
				message or body,
			)
		except Exception:
			pass

	return {"sent": created, "log": log.name}
