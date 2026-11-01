# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import bulk_insert

from central.api.pilot import pilot_credential_auth
from central.iam import can_on_any_server, is_active_team_member, resolve_team, user_has_operator_bypass
from central.notification import CATEGORIES
from central.notification.doctype.notification_digest_setting.notification_digest_setting import (
	NotificationDigestSetting,
)
from central.notification.doctype.user_notification_preference.user_notification_preference import (
	UserNotificationPreference,
)

MARK_READ_BATCH_SIZE = 500
PILOT_REPORTABLE_CATEGORIES = ("Server",)


def _require_member(user: str, team: str) -> None:
	"""Gate the preference + feed endpoints on team membership (operators bypass)."""
	if user_has_operator_bypass(user):
		return
	if not is_active_team_member(user, team):
		frappe.throw(
			_("You are not a member of this team."),
			frappe.PermissionError,
		)


def _member_team(team: str | None) -> str:
	"""Resolve the acting team (given, or the caller's sole team) and gate on
	membership. Feed content is further capability-filtered per row downstream, so
	a member only ever sees the notifications their grants permit."""
	user = frappe.session.user
	team = resolve_team(user, team)
	_require_member(user, team)

	return team


@frappe.whitelist(methods=["POST"])
def save_user_preferences(team: str, preferences: list[dict], digest_hour: int | None = None) -> dict:
	"""Save the caller's notification preferences and one digest hour for *team*."""
	user = frappe.session.user
	_require_member(user, team)
	saved = []
	# Serialize preference upserts for this team. The unique constraint remains the
	# final guard when separate requests race.
	frappe.db.get_value("Team", team, "name", for_update=True)
	if digest_hour is not None:
		NotificationDigestSetting.upsert(user, team, digest_hour)
	for pref in preferences:
		email = bool(frappe.utils.cint(pref.get("email_enabled", 1)))
		in_app = bool(frappe.utils.cint(pref.get("in_app_enabled", 1)))
		events = None
		if "events" in pref:
			events = [
				{"event_type": event.get("event_type"), "email_enabled": 0}
				for event in pref["events"] or []
				if not frappe.utils.cint(event.get("email_enabled", 0))
			]

		doc = UserNotificationPreference.upsert(
			user,
			team,
			pref.get("category"),
			email,
			in_app,
			pref.get("frequency"),
			events,
		)
		saved.append(
			{
				"name": doc.name,
				"category": doc.category,
				"email_enabled": doc.email_enabled,
				"in_app_enabled": doc.in_app_enabled,
				"frequency": doc.frequency,
				"events": [
					{"event_type": row.event_type, "email_enabled": row.email_enabled} for row in doc.events
				],
			}
		)

	return {
		"saved": True,
		"digest_hour": NotificationDigestSetting.get_hour(user, team),
		"preferences": saved,
	}


@frappe.whitelist()
def get_user_preferences(team: str) -> dict:
	"""Return the calling user's notification preferences and the event catalog for *team*."""
	user = frappe.session.user
	_require_member(user, team)
	loaded = UserNotificationPreference.load_for_users(team, [user], user_scoped=True)
	preferences = [
		{
			"category": category,
			"email_enabled": int(preference["email_enabled"]),
			"in_app_enabled": int(preference["in_app_enabled"]),
			"frequency": preference["frequency"],
			"events": [
				{"event_type": event_type, "email_enabled": int(email_enabled)}
				for event_type, email_enabled in preference["events"].items()
			],
		}
		for (loaded_user, category), preference in sorted(
			loaded.items(), key=lambda item: CATEGORIES.index(item[0][1])
		)
		if loaded_user == user
	]

	time_zone = frappe.db.get_value("User", user, "time_zone") or frappe.utils.get_system_timezone() or "UTC"
	return {
		"time_zone": time_zone,
		"digest_hour": NotificationDigestSetting.get_hour(user, team),
		"preferences": preferences,
		"catalog": _event_catalog(user, team),
	}


def _event_catalog(user: str, team: str) -> list[dict]:
	# The event registry is global, so customers read this catalog without desk permissions.
	events = frappe.get_all(
		"Notification Event Type",
		fields=[
			"event_type",
			"category",
			"severity",
			"required_cap",
			"direct_recipients",
			"in_app_title",
			"is_critical",
		],
		order_by="event_type asc",
	)
	allowed = _held_capabilities(user, team, events)
	by_category = {category: [] for category in CATEGORIES}
	for event in events:
		by_category[event.category].append(_catalog_entry(event, allowed))
	return [
		{"category": category, "label": category, "events": by_category[category]}
		for category in CATEGORIES
		if by_category[category]
	]


def _held_capabilities(user: str, team: str, events: list[frappe._dict]) -> dict[str, bool]:
	capabilities = {
		event.required_cap
		for event in events
		if event.required_cap and event.direct_recipients != "Affected User"
	}
	return {capability: can_on_any_server(user, team, capability) for capability in capabilities}


def _catalog_entry(event: frappe._dict, allowed: dict[str, bool]) -> dict:
	can_receive = (
		not event.required_cap or event.direct_recipients == "Affected User" or allowed[event.required_cap]
	)
	title = event.in_app_title
	if "{{" in title or "{%" in title:
		title = frappe.unscrub(event.event_type)
	return {
		"event_type": event.event_type,
		"title": title,
		"severity": event.severity,
		"is_critical": event.is_critical,
		"can_receive": int(can_receive),
	}


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def report_pilot_event(
	event_type: str,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	context: dict | None = None,
) -> dict:
	"""Raise a server or site event from a Pilot. The team and server come from the
	Pilot's credential, never from the body. Billing and Team events are refused, so a
	compromised bench cannot email a whole team."""
	credential = frappe.local.pilot_credential
	team = credential.team
	event = frappe.db.get_value(
		"Notification Event Type", event_type, ["category", "reportable_by"], as_dict=True
	)
	if not event or event.reportable_by != "Pilot" or event.category not in PILOT_REPORTABLE_CATEGORIES:
		frappe.throw(_("This event type cannot be reported by a pilot."), frappe.PermissionError)
	from central.notification.engine import dispatch

	return dispatch(
		team,
		event_type,
		message=message,
		context=context,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		server=credential.server,
	)


# The team's feed of billing and server events, gated on membership and on each row's capability.


@frappe.whitelist()
def list_notifications(
	team: str | None = None,
	start: int = 0,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""One page of the team's feed, newest first, with ``has_next_page``. A member sees only
	the notifications whose capability they hold."""
	from central.notification import list_notifications as _list

	return _list(
		_member_team(team),
		start=start,
		limit=limit,
		category=category,
		unread_only=unread_only,
	)


@frappe.whitelist()
def notification_badge(team: str | None = None) -> dict:
	"""Lightweight unread count for the console bell badge (no item payload)."""
	from central.notification import unread_count

	return {"unread": unread_count(_member_team(team), user=frappe.session.user)}


@frappe.whitelist(methods=["POST"])
def mark_notification_read(name: str, team: str | None = None, read: bool = True) -> dict:
	"""Mark one of the team's notifications read (or unread). Read state is per-user:
	each member creates/removes a ``Notification Read`` record rather than mutating
	the shared ``is_read`` flag."""
	team = _member_team(team)
	if frappe.db.get_value("Team Notification", name, "team") != team:
		frappe.throw(_("Notification not found for this team."), frappe.PermissionError)

	user = frappe.session.user
	read = bool(frappe.utils.cint(read))

	if read:
		# A read marker is the caller's own internal row; the check above keeps it to this team.
		bulk_insert(
			"Notification Read",
			[_read_marker(user, name, frappe.utils.now_datetime())],
			ignore_duplicates=True,
		)
	else:
		frappe.db.delete("Notification Read", {"user": user, "notification": name})

	from central.notification import unread_count

	return {"ok": True, "unread": unread_count(team, user=user)}


@frappe.whitelist(methods=["POST"])
def mark_all_notifications_read(team: str | None = None) -> dict:
	"""Mark every visible notification for the user read — the bell's 'clear' action.
	Per-user ``Notification Read`` records, so one member clearing does not affect
	others."""
	team = _member_team(team)
	from central.notification import unread_count, unread_names

	user = frappe.session.user
	before = unread_count(team, user=user)
	now = frappe.utils.now_datetime()
	while names := unread_names(team, user, limit=MARK_READ_BATCH_SIZE):
		# Read markers are internal rows; the query returns only notifications visible to this user.
		bulk_insert(
			"Notification Read",
			[_read_marker(user, name, now) for name in names],
			ignore_duplicates=True,
			chunk_size=MARK_READ_BATCH_SIZE,
		)

	unread = unread_count(team, user=user)

	return {"ok": True, "updated": before - unread, "unread": unread}


def _read_marker(user: str, notification: str, read_at):
	doc = frappe.get_doc(
		{
			"doctype": "Notification Read",
			"user": user,
			"notification": notification,
			"read_at": read_at,
		}
	)
	doc.set_new_name()

	return doc
