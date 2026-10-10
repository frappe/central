# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.sso import central_url


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
	"""Record one notification event for *team* and email the qualified members.

	A duplicate returns ``reason="duplicate"`` and sends no email. *server* scopes the event
	when the reference does not name one."""
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
		# create_notification is the only Team Notification insert path.
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
	"""True if the same event for the same reference was created in the dedup window.

	Read state is per user, so the window replaces the shared ``is_read`` flag. A later,
	different event for the reference means the state changed, so it is not a duplicate."""
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
	"""Email each active member who has the event's capability and has email enabled.

	For ``direct_recipients = "Affected User"``, only *affected_user* gets the email, without a
	capability check. Returns ``{"queued": N, "attempted": N, "failed": N}``."""
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
	"""Nudge the sockets of the team's active members only.

	A publish without a user goes to every Desk user of every tenant, so each member gets
	their own. The payload names only the team; the feed comes from the permission-filtered API."""
	for member in _get_active_members(team):
		frappe.publish_realtime(
			f"team_notification:{team}",
			{"team": team},
			user=member,
			after_commit=True,
		)


def _email_enabled(user: str, team: str, category: str) -> bool:
	"""Whether the user gets email for this category. No preference record means yes."""
	pref = frappe.db.get_value(
		"User Notification Preference",
		{"user": user, "team": team, "category": category},
		"email_enabled",
	)
	return pref is None or bool(pref)


def _notification_email(event, ctx, message=None) -> tuple[str, str]:
	"""Subject and branded HTML body, rendered from the event's own in-app fields."""
	# The email uses the same sentence as the in-app notification.
	ctx = {**ctx, "message": message or ctx.get("message") or ""}
	subject = _render_template(event.in_app_title, ctx) or event.name
	text = (_render_template(event.in_app_body, ctx) or "").strip()
	route = _render_template(event.action_route, ctx) if event.action_route else None
	# nosemgrep: frappe-ssti -- a fixed template that ships with the app, filled only with values.
	body = frappe.render_template(
		"templates/emails/notification.html",
		{
			"title": subject,
			"body": text,
			"action_label": event.action_label,
			"action_url": f"{central_url()}/dashboard{route}" if route else None,
		},
	)

	return subject, body


def _send_member_email(
	user, team, event, ctx, *, message=None, reference_doctype=None, reference_name=None
) -> bool:
	"""Queue one notification email for *user*. Return False when queuing fails."""
	subject, body = _notification_email(event, ctx, message)

	try:
		frappe.sendmail(
			recipients=[user],
			subject=subject,
			message=body,
		)
		return True
	except Exception:
		# Delivery is best effort, but a failure must leave an error log.
		frappe.log_error(title=f"Notification email send failed: {event.name} -> {user}")
		return False
