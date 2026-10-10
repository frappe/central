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


def queue_event(
	team: str,
	event_type: str,
	*,
	message: str | None = None,
	context: dict | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	affected_user: str | None = None,
) -> None:
	"""Queue one event after its owning resource transaction commits."""
	identity = reference_name or affected_user or team
	frappe.enqueue(
		dispatch,
		team=team,
		event_type=event_type,
		message=message,
		context=context,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		affected_user=affected_user,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"notification:{event_type}:{identity}",
		deduplicate=True,
	)


def dispatch(
	team: str,
	event_type: str,
	*,
	message: str | None = None,
	context: dict | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	server: str | None = None,
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

	The result always includes creation and email queue counts. A duplicate returns
	``reason="duplicate"`` with zero email attempts.

	*server* scopes the event when the reference does not name one.
	"""
	from central.notification import get_reference_server

	server = server or get_reference_server(reference_doctype, reference_name)
	ctx = _resolve_context(team, event_type, context, reference_name, reference_doctype)
	ctx["server_title"] = _get_server_title(server)
	ctx["reference_title"] = _get_reference_title(team, reference_doctype, reference_name)
	ctx["message"] = message or ""

	event = _get_event_type(event_type)
	if not event:
		frappe.throw(
			_("Unknown notification event type: {0}").format(event_type),
			frappe.DoesNotExistError,
		)

	# Deduplication: suppress if an unread notification with the same
	# event_type and reference_name already exists for this team.
	if _is_duplicate(team, event_type, reference_name, server):
		return {
			"created": False,
			"reason": "duplicate",
			"notification": None,
			"emails_queued": 0,
			"email_attempted": 0,
			"email_failed": 0,
		}

	title = _render_template(event.in_app_title, ctx)
	body = _render_template(event.in_app_body, ctx)

	doc = None
	if event.create_in_app:
		# One writer: dispatch resolves the event type from the registry, then hands
		# the row to create_notification (the single Team Notification insert) rather
		# than building its own — so there is one insert path, not two.
		from central.notification import create_notification

		doc = create_notification(
			team,
			title,
			category=event.category,
			event_type=event_type,
			severity=event.severity,
			required_cap=event.required_cap,
			message=body,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			server=server,
			action_label=event.action_label,
			action_route=_render_template(event.action_route, ctx) if event.action_route else None,
			publish=True,
		)

	email_result = _fan_out_emails(
		team,
		event,
		ctx,
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		server=server,
		affected_user=affected_user,
	)

	return {
		"created": bool(doc),
		"notification": doc.name if doc else None,
		"title": title,
		"body": body,
		"emails_queued": email_result["queued"],
		"email_attempted": email_result["attempted"],
		"email_failed": email_result["failed"],
	}


def _get_event_type(event_type: str):
	"""Fetch the Event Type registry row."""
	return frappe.db.get_value(
		"Notification Event Type",
		event_type,
		[
			"name",
			"category",
			"severity",
			"required_cap",
			"direct_recipients",
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
		"team_name": frappe.db.get_value("Team", team, "team_name") or team,
		"event_type": event_type,
		"reference_name": reference_name or "",
		"reference_doctype": reference_doctype or "",
	}
	if context:
		ctx["context"] = context
	return ctx


# Only these references render a title. A team-owned one must belong to the event's team,
# because a Pilot names its own reference and could name another team's record.
REFERENCE_TITLE_FIELDS = {
	"Virtual Machine": "title",
	"VM Snapshot": "title",
	"Site": "site_name",
	"Region": "display_name",
}
TEAM_OWNED_REFERENCES = {"Virtual Machine", "VM Snapshot", "Site"}


def _get_server_title(server: str | None) -> str:
	"""The server's title, or its name when it has none."""
	if not server:
		return ""
	return frappe.db.get_value("Virtual Machine", server, "title") or server


def _get_reference_title(team: str, reference_doctype: str | None, reference_name: str | None) -> str:
	"""The reference's title, or its name when the record is unknown, untitled, or another team's."""
	if not reference_name:
		return ""
	title_field = REFERENCE_TITLE_FIELDS.get(reference_doctype or "")
	if not title_field:
		return reference_name

	is_team_owned = reference_doctype in TEAM_OWNED_REFERENCES
	fields = [title_field, "team"] if is_team_owned else [title_field]
	row = frappe.db.get_value(reference_doctype, reference_name, fields, as_dict=True)
	if not row or (is_team_owned and row.team != team):
		return reference_name
	return row[title_field] or reference_name


def _render_template(template_str: str | None, ctx: dict) -> str | None:
	"""Render a Jinja template string with *ctx*. Returns None if template is empty."""
	if not template_str:
		return None
	# nosemgrep: frappe-ssti -- templates come from the System Manager-only Notification Event Type doctype (repo fixtures), never from users.
	return frappe.render_template(template_str, ctx)


DEDUP_WINDOW_MINUTES = 60


def _is_duplicate(team, event_type, reference_name, server=None) -> bool:
	"""True if a Team Notification for the same event+ref was created recently.

	Uses a time window instead of ``is_read`` because read state is now
	per-user (``Notification Read``) — the shared ``is_read`` flag is never
	mutated and stays ``0`` forever.

	When a different event type for the same reference was created after the
	first occurrence (e.g., ``site_recovered`` after ``backup_failure``), the
	state has changed and a new notification is allowed through.

	A known *server* narrows the match, so equal names on two servers stay distinct.
	"""
	if not reference_name:
		return False
	cutoff = frappe.utils.add_to_date(None, minutes=-DEDUP_WINDOW_MINUTES)
	subject = {"team": team, "reference_name": reference_name}
	if server:
		subject["server"] = server
	existing = frappe.db.get_value(
		"Team Notification",
		{**subject, "event_type": event_type, "creation": (">=", cutoff)},
		"creation",
	)
	if not existing:
		return False
	# A different event_type for the same reference means state changed
	# since the first occurrence — allow the new notification through.
	state_changed = frappe.db.exists(
		"Team Notification",
		{**subject, "event_type": ("!=", event_type), "creation": (">", existing)},
	)
	return not state_changed


def _fan_out_emails(
	team,
	event,
	ctx,
	*,
	message=None,
	reference_doctype=None,
	reference_name=None,
	server=None,
	affected_user=None,
) -> dict:
	"""Send individual emails to each qualified team member.

	Members are qualified by:
	  1. Being an active member of the team.
	  2. Having the required capability (via ``iam.can``), on the referenced server when
	     the event is about one.
	  3. Having ``email_enabled`` in their ``UserNotificationPreference``
	     (default: enabled when no preference record exists).

	For ``direct_recipients = "Affected User"``, only *affected_user* receives
	the email — capability is bypassed for that user and no other members are
	contacted.

	Returns ``{"queued": N, "attempted": N, "failed": N}``.
	"""
	from central.iam import can

	result = {"queued": 0, "attempted": 0, "failed": 0}

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
				result["queued"] = 1
			else:
				result["failed"] = 1
		return result

	members = _get_active_members(team)
	if not members:
		return result

	for member_user in members:
		if event.required_cap and not can(member_user, team, event.required_cap, server=server):
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
			result["queued"] += 1
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


def publish_team_nudge(team: str) -> None:
	"""Nudge only the team's active members' sockets, not the whole site.

	``frappe.publish_realtime`` without a ``user``/``room`` broadcasts to the
	site room (every Desk user, all tenants). Target each member's
	``user:<email>`` room instead — every socket auto-joins its own user room
	on connect, so the dashboard's ``team_notification:<team>`` listener fires
	only for team members. The payload stays team-only; feed content is
	fetched over the permission-filtered API.
	"""
	for member in _get_active_members(team):
		frappe.publish_realtime(
			f"team_notification:{team}",
			{"team": team},
			user=member,
			after_commit=True,
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


def _notification_email(event, ctx, message=None) -> tuple[str, str]:
	"""Subject and branded HTML body for an event with no bespoke Email Template.

	Renders templates/emails/notification.html from the fields the event already
	carries, so a newly added event type is styled without a new template.
	"""
	# The email says the same sentence as the in-app notification. A body may use
	# `message` anywhere in it, so it is never split out of the sentence.
	ctx = {**ctx, "message": message or ctx.get("message") or ""}
	subject = _render_template(event.in_app_title, ctx) or event.name
	text = (_render_template(event.in_app_body, ctx) or "").strip()
	route = _render_template(event.action_route, ctx) if event.action_route else None
	body = frappe.render_template(
		"templates/emails/notification.html",
		{
			"title": subject,
			"body": text,
			"action_label": event.action_label,
			"action_url": f"{frappe.utils.get_url()}/dashboard{route}" if route else None,
		},
	)
	return subject, body


def _send_member_email(
	user, team, event, ctx, *, message=None, reference_doctype=None, reference_name=None
) -> bool:
	"""Render the shared notification template and queue one email for *user*.

	Best-effort: if the outgoing email account is not configured the
	notification is still recorded in the feed; the email is simply skipped.

	Returns True if Frappe accepted the email for delivery, False if queuing failed.

	Every event uses templates/emails/notification.html. The event registry supplies
	the title, body and action without maintaining a second template system.
	"""
	subject, body = _notification_email(event, ctx, message)

	try:
		frappe.sendmail(
			recipients=[user],
			subject=subject,
			message=body,
		)
		return True
	except Exception:
		# Best-effort delivery, but never fail silently — a missing outgoing account
		# or a send error must leave a trace to diagnose (retry/backoff is a later phase).
		frappe.log_error(title=f"Notification email send failed: {event.name} -> {user}")
		return False
