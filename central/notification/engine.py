# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.translate import get_user_lang, print_language
from frappe.utils import escape_html

from central.errors import build_envelope
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
	ctx["server"] = server or ""
	ctx["server_title"] = _get_server_title(server)
	ctx["reference_title"] = _get_reference_title(team, reference_doctype, reference_name)
	ctx["message"] = message or ""

	event = get_event_type(event_type)
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

	reader_ctx = _get_reader_context(ctx)
	title = _render_template(event.in_app_title, reader_ctx)
	body = _render_template(event.in_app_body, reader_ctx)

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
			template_context=ctx,
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


# The copy a reader sees. `extractor.extract` adds it from the fixture to the translation catalog.
TRANSLATED_FIELDS = ("in_app_title", "in_app_body", "action_label")


def get_event_type(event_type: str):
	"""Fetch the Event Type registry row, with its copy in the current language."""
	event = frappe.db.get_value(
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
			"is_critical",
			"reportable_by",
		],
		as_dict=True,
	)
	if not event:
		return None

	# Translate the Jinja source, so a translation keeps its {{ placeholders }}.
	for field in TRANSLATED_FIELDS:
		if event[field]:
			event[field] = _(event[field])

	return event


def render_for_reader(rows: list[frappe._dict]) -> None:
	"""Fill each feed row's title, message and action label again in the current language,
	from the context the row was created with. A row without a context keeps its stored copy."""
	events = {}
	failed_events = set()
	for row in rows:
		ctx = row.pop("template_context", None)
		if not (ctx and row.event_type) or row.event_type in failed_events:
			continue

		if row.event_type not in events:
			events[row.event_type] = get_event_type(row.event_type)
		event = events[row.event_type]
		if not event:
			continue

		try:
			ctx = _get_reader_context(frappe.parse_json(ctx))
			title = _render_template(event.in_app_title, ctx)
			message = _render_template(event.in_app_body, ctx)
		except Exception:
			# A broken translation of one template must not break the whole feed.
			frappe.log_error(title=f"Notification render failed: {row.event_type} ({frappe.local.lang})")
			failed_events.add(row.event_type)
			continue

		row.title = title or row.title
		row.message = message
		row.action_label = event.action_label


def _get_reader_context(ctx: dict) -> dict:
	"""The template context with a Resource Action's error code turned into its catalog
	sentence and its action into a word, both in the current language."""
	context = ctx.get("context") or {}
	if not context.get("error_code"):
		return ctx

	envelope = build_envelope(
		context["error_code"], action=context.get("action"), resource_id=context.get("resource_id")
	)
	return {
		**ctx,
		"message": ctx.get("message") or envelope["message"],
		"context": {**context, "action": _(context["action"]) if context.get("action") else ""},
	}


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

	# A site is named by the address its owner opens, which the email's button also opens.
	if reference_doctype == "Site":
		return urlsplit(frappe.get_doc("Site", reference_name).routed_url).hostname

	return row[title_field] or reference_name


def _render_template(template_str: str | None, ctx: dict) -> str | None:
	"""Render a Jinja template string with *ctx*. Returns None if template is empty."""
	if not template_str:
		return None
	# nosemgrep: frappe-ssti -- templates come from the System Manager-only Notification Event Type doctype (repo fixtures) or its Translation records, never from customers; render_template is sandboxed.
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
	"""Queue the email to each recipient, sent after the caller's transaction commits.

	Rendering an email is slow, and the caller often holds a lock on money records, so only the
	recipients are decided here. Returns ``{"queued": N, "attempted": N, "failed": 0}``: a send
	fails only later, in the job, and leaves an Error Log there."""
	recipients = _email_recipients(team, event, server=server, affected_user=affected_user)
	if recipients:
		# After commit only: a rollback drops the job, so no mail goes out for a change that never happened.
		frappe.enqueue(
			send_notification_emails,
			queue="short",
			enqueue_after_commit=True,
			recipients=recipients,
			event_type=event.name,
			ctx=ctx,
			message=message,
		)
	return {"queued": len(recipients), "attempted": len(recipients), "failed": 0}


def _email_recipients(team, event, *, server=None, affected_user=None) -> list[str]:
	"""The users who get this event by email.

	For ``direct_recipients = "Affected User"``, only *affected_user*, without a capability check.
	Otherwise each active member with the event's capability. Either way, only users who want it now."""
	from central.iam import can
	from central.notification.doctype.user_notification_preference.user_notification_preference import (
		UserNotificationPreference,
	)

	if event.direct_recipients == "Affected User":
		users = [affected_user] if affected_user else []
	else:
		users = [
			user
			for user in _get_active_members(team)
			if not event.required_cap or can(user, team, event.required_cap, server=server)
		]
	preferences = UserNotificationPreference.load_for_users(team, users)
	return [user for user in users if _is_emailed_instantly(preferences.get((user, event.category)), event)]


def send_notification_emails(recipients: list[str], event_type: str, ctx: dict, message=None) -> None:
	"""Background job: render the event's email once per language and send each recipient theirs."""
	recipients_by_language = defaultdict(list)
	for user in recipients:
		recipients_by_language[get_user_lang(user)].append(user)

	for language, users in recipients_by_language.items():
		with print_language(language):
			event = get_event_type(event_type)
			subject, body = _notification_email(event, ctx, message)

		for user in users:
			try:
				frappe.sendmail(recipients=[user], subject=subject, message=body)
			except Exception:
				# Delivery is best effort, but a failure must leave an error log.
				frappe.log_error(title=f"Notification email send failed: {event.name} -> {user}")


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


def _is_emailed_instantly(preference: dict | None, event: frappe._dict) -> bool:
	"""No preference means yes. A digest event waits for the digest, which reads it from the feed.

	The feed row is team-wide, so an Affected User event cannot wait for the digest."""
	if preference is None or event.is_critical:
		return True
	if not preference["email_enabled"]:
		return False
	if not preference["events"].get(event.name, True):
		return False
	return (
		preference["frequency"] == "Instant"
		or not event.create_in_app
		or event.direct_recipients == "Affected User"
	)


def _notification_email(event, ctx, message=None) -> tuple[str, str]:
	"""Subject and HTML body, with the branding and notes of the Site's product."""
	from central.signups.doctype.product.product import GETTING_STARTED_EMAILS, get_email_product

	# The email uses the same sentence as the in-app notification.
	ctx = _get_reader_context({**ctx, "message": message or ctx.get("message") or ""})
	site = _get_email_site(ctx["team"], ctx["reference_doctype"], ctx["reference_name"])
	product = get_email_product(site.product) if site else None
	extras = product.get_email_extras(event.name) if product else {}
	if site and event.name in GETTING_STARTED_EMAILS:
		landing_route = product.landing_route if product else None
		extras["site_url"] = site.routed_url + (landing_route or "")

	return render_notification_email(event, ctx, extras)


def render_notification_email(event, ctx: dict, extras: dict) -> tuple[str, str]:
	"""Subject and branded HTML body, rendered from the event's own in-app fields. Context
	values such as a product title or a Pilot message are text, so the HTML escapes them."""
	subject = _render_template(event.in_app_title, ctx) or event.name
	text = (_render_template(event.in_app_body, ctx) or "").strip()
	route = _render_template(event.action_route, ctx) if event.action_route else None
	action_url = extras.get("site_url") or (f"{central_url()}/dashboard{route}" if route else None)
	# nosemgrep: frappe-ssti -- a fixed template that ships with the app, filled only with values.
	body = frappe.render_template(
		"templates/emails/notification.html",
		{
			"title": escape_html(subject),
			"paragraphs": [escape_html(part.strip()) for part in text.split("\n\n") if part.strip()],
			"notes": extras.get("notes") or [],
			"brand": extras.get("brand"),
			"action_label": event.action_label,
			"action_url": escape_html(action_url) if action_url else None,
			"getting_started_url": extras.get("getting_started_url"),
		},
	)

	return subject, body


def _get_email_site(team: str, reference_doctype: str, reference_name: str):
	"""Resolve the event's Site only within its Team, because a Pilot can name another team's Site."""
	if reference_doctype != "Site" or not reference_name:
		return None

	name = frappe.db.exists("Site", {"name": reference_name, "team": team})
	if not name:
		return None

	return frappe.get_doc("Site", name)
