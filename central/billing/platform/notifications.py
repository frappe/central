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
	# nosemgrep: frappe-ssti -- in_app_body comes from the System Manager-only Notification Event Type doctype, never from users.
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
	# Pascal Case (e.g. "Payment Success" → "payment_success"). Hyphens in
	# display names ("Pre-debit Notice") map to underscores too.
	slug = event_type.lower().replace(" ", "_").replace("-", "_")

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
	queued = result.get("emails_queued", 0)
	failed = result.get("email_failed", 0)
	status = "Failed" if failed else "Queued" if queued else "Suppressed"
	log = frappe.get_doc(
		{
			"doctype": "Billing Notification Log",
			"team": team,
			"event_type": event_type,
			"channel": "email",
			"status": status,
			"subject": result.get("title") or event_type,
			"message": message or body,
			"reference_doctype": reference_doctype,
			"reference_name": ref,
			"queued_at": frappe.utils.now_datetime() if queued else None,
		}
	)
	# This internal audit row records the engine result on behalf of the billing operation.
	log.insert(ignore_permissions=True)

	if reference_doctype and ref:
		try:
			frappe.get_doc(reference_doctype, ref).add_comment(
				"Info",
				message or body,
			)
		except Exception:
			frappe.log_error(
				title="Notification audit comment failed",
				reference_doctype=reference_doctype,
				reference_name=ref,
			)

	return {"notified": created, "email_status": status, "log": log.name}
