# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification engine — dispatches events into the in-app feed and email channel.

The engine is the single entry point for all notification-producing subsystems
(billing, server/infra, pilot). It reads the ``Notification Event Type`` registry
for templates and capability requirements, deduplicates in-app entries, writes
one ``Team Notification`` per event, and fans out emails per qualified team member.
"""

import frappe
from frappe import _


def dispatch(
	team: str,
	event_type: str,
	*,
	message: str | None = None,
	context: dict | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	affected_user: str | None = None,
) -> dict:
	"""Dispatch a notification event for *team*.

	Looks up the ``Notification Event Type`` registry, renders the in-app title
	and body from Jinja templates, deduplicates (skips if an unread notification
	with the same event_type + reference_name already exists), writes one
	``Team Notification`` with the event's ``required_cap``, and fans out emails
	to qualified team members honoring their ``UserNotificationPreference``.

	When ``direct_recipients = "Affected User"``, only *affected_user* receives
	the email (capability check is bypassed for that user).  All other members
	receive nothing for that event.

	Returns ``{"created": True, "notification": <name>}`` on success, or
	``{"created": False, "reason": "duplicate"}`` when dedup fires.
	"""
	ctx = _resolve_context(team, event_type, context, reference_name, reference_doctype)
	ctx["message"] = message or ""

	event = _get_event_type(event_type)
	if not event:
		frappe.throw(
			_("Unknown notification event type: {0}").format(event_type),
			frappe.DoesNotExistError,
		)

	# Deduplication: suppress if an unread notification with the same
	# event_type and reference_name already exists for this team.
	if _is_duplicate(team, event_type, reference_name):
		return {"created": False, "reason": "duplicate"}

	title = _render_template(event.in_app_title, ctx)
	body = _render_template(event.in_app_body, ctx)

	doc = None
	if event.create_in_app:
		doc = frappe.get_doc(
			{
				"doctype": "Team Notification",
				"team": team,
				"category": event.category,
				"event_type": event_type,
				"severity": event.severity,
				"required_cap": event.required_cap,
				"title": title,
				"message": body,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"action_label": event.action_label,
				"action_route": _render_template(event.action_route, ctx) if event.action_route else None,
				"is_read": 0,
			}
		).insert(ignore_permissions=True)

		frappe.publish_realtime(f"team_notification:{team}", {"team": team}, after_commit=True)

	email_result = _fan_out_emails(
		team,
		event,
		ctx,
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		affected_user=affected_user,
	)

	return {
		"created": bool(doc),
		"notification": doc.name if doc else None,
		"title": title,
		"body": body,
		"emails_sent": email_result["sent"],
		"email_attempted": email_result["attempted"],
		"email_failed": email_result["failed"],
	}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def ensure_event_type(
	event_type: str,
	*,
	category: str,
	severity: str,
	required_cap: str,
	in_app_title: str,
	in_app_body: str,
	action_label: str | None = None,
	action_route: str | None = None,
	direct_recipients: str = "None",
	create_in_app: bool = True,
	email_template: str | None = None,
):
	"""Create the ``Notification Event Type`` row if it doesn't already exist.

	Callers should invoke this before ``dispatch()`` when the fixture may not
	have been loaded (e.g. in tests or isolated background jobs).  The
	insertion is a no-op when the row is already present.
	"""
	if frappe.db.exists("Notification Event Type", event_type):
		return
	frappe.get_doc(
		{
			"doctype": "Notification Event Type",
			"event_type": event_type,
			"category": category,
			"severity": severity,
			"required_cap": required_cap,
			"in_app_title": in_app_title,
			"in_app_body": in_app_body,
			"action_label": action_label,
			"action_route": action_route,
			"direct_recipients": direct_recipients,
			"create_in_app": int(create_in_app),
			"email_template": email_template,
		}
	).insert(ignore_permissions=True)


def _get_event_type(event_type: str):
	"""Fetch the Event Type registry row (cached per request)."""
	return frappe.db.get_value(
		"Notification Event Type",
		event_type,
		[
			"name",
			"category",
			"severity",
			"required_cap",
			"direct_recipients",
			"email_template",
			"in_app_title",
			"in_app_body",
			"action_label",
			"action_route",
			"create_in_app",
		],
		as_dict=True,
	)


def _resolve_context(team, event_type, context, reference_name, reference_doctype=None):
	"""Build the template context dict shared by all Jinja renders."""
	ctx = {
		"team": team,
		"event_type": event_type,
		"reference_name": reference_name or "",
		"reference_doctype": reference_doctype or "",
	}
	if context:
		ctx["context"] = context
	return ctx


def _render_template(template_str: str | None, ctx: dict) -> str | None:
	"""Render a Jinja template string with *ctx*. Returns None if template is empty."""
	if not template_str:
		return None
	return frappe.render_template(template_str, ctx)


DEDUP_WINDOW_MINUTES = 60


def _is_duplicate(team, event_type, reference_name) -> bool:
	"""True if a Team Notification for the same event+ref was created recently.

	Uses a time window instead of ``is_read`` because read state is now
	per-user (``Notification Read``) — the shared ``is_read`` flag is never
	mutated and stays ``0`` forever.

	When a different event type for the same reference was created after the
	first occurrence (e.g., ``site_recovered`` after ``backup_failure``), the
	state has changed and a new notification is allowed through.
	"""
	if not reference_name:
		return False
	cutoff = frappe.utils.add_to_date(None, minutes=-DEDUP_WINDOW_MINUTES)
	existing = frappe.db.get_value(
		"Team Notification",
		{
			"team": team,
			"event_type": event_type,
			"reference_name": reference_name,
			"creation": (">=", cutoff),
		},
		"creation",
	)
	if not existing:
		return False
	# A different event_type for the same reference means state changed
	# since the first occurrence — allow the new notification through.
	state_changed = frappe.db.exists(
		"Team Notification",
		{
			"team": team,
			"reference_name": reference_name,
			"event_type": ("!=", event_type),
			"creation": (">", existing),
		},
	)
	return not state_changed


def _fan_out_emails(
	team, event, ctx, *, message=None, reference_doctype=None, reference_name=None, affected_user=None
) -> dict:
	"""Send individual emails to each qualified team member.

	Members are qualified by:
	  1. Being an active member of the team.
	  2. Having the required capability (via ``iam.can``).
	  3. Having ``email_enabled`` in their ``UserNotificationPreference``
	     (default: enabled when no preference record exists).

	For ``direct_recipients = "Affected User"``, only *affected_user* receives
	the email — capability is bypassed for that user and no other members are
	contacted.

	Returns ``{"sent": N, "attempted": N, "failed": N}``.
	"""
	from central.iam import can

	result = {"sent": 0, "attempted": 0, "failed": 0}

	if event.direct_recipients == "Affected User":
		if affected_user and _email_enabled(affected_user, team, event.category):
			ok = _send_member_email(
				affected_user,
				team,
				event,
				ctx,
				message=message,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
			)
			result["attempted"] = 1
			if ok:
				result["sent"] = 1
			else:
				result["failed"] = 1
		return result

	members = _get_active_members(team)
	if not members:
		return result

	for member_user in members:
		if event.required_cap and not can(member_user, team, event.required_cap):
			continue

		if not _email_enabled(member_user, team, event.category):
			continue

		result["attempted"] += 1
		ok = _send_member_email(
			member_user,
			team,
			event,
			ctx,
			message=message,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
		if ok:
			result["sent"] += 1
		else:
			result["failed"] += 1

	return result


def _get_active_members(team: str) -> list[str]:
	"""Return the user emails of all active team members."""
	return frappe.get_all(
		"Team Member",
		filters={"parent": team, "parenttype": "Team", "status": "Active"},
		pluck="user",
	)


def _email_enabled(user: str, team: str, category: str) -> bool:
	"""Check if the user has email enabled for this category.

	Returns True when no preference record exists (opt-out model).
	"""
	pref = frappe.db.get_value(
		"User Notification Preference",
		{"user": user, "team": team, "category": category},
		"email_enabled",
	)
	return pref is None or bool(pref)


def _send_member_email(
	user, team, event, ctx, *, message=None, reference_doctype=None, reference_name=None
) -> bool:
	"""Render and queue a single email for *user*.

	Best-effort: if the outgoing email account is not configured the
	notification is still recorded in the feed; the email is simply skipped.

	Returns True if the email was sent successfully, False if it failed.

	When the Event Type has an ``email_template`` link, the Frappe Email
	Template DocType is used for subject/body rendering.  Otherwise the
	in-app Jinja templates are used (with the ``message`` override when
	provided).
	"""
	if event.email_template:
		try:
			from frappe.email.doctype.email_template.email_template import (
				get_email_template,
			)

			rendered = get_email_template(event.email_template, ctx)
			subject = rendered["subject"]
			body = rendered["message"]
		except Exception:
			subject = _render_template(event.in_app_title, ctx) or event.event_type
			body = message or _render_template(event.in_app_body, ctx) or ctx.get("message", "")
	else:
		subject = _render_template(event.in_app_title, ctx) or event.event_type
		body = message or _render_template(event.in_app_body, ctx) or ctx.get("message", "")

	try:
		frappe.sendmail(
			recipients=[user],
			subject=subject,
			message=body,
		)
		return True
	except Exception:
		return False
