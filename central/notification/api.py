# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import bulk_insert

from central.api.pilot import pilot_credential_auth
from central.iam import is_active_team_member, resolve_team, user_has_operator_bypass
from central.notification import CATEGORIES
from central.notification.doctype.user_notification_preference.user_notification_preference import (
	UserNotificationPreference,
)

MARK_READ_BATCH_SIZE = 500


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
def save_user_preferences(team: str, preferences: list[dict]) -> dict:
	"""Save the caller's notification preferences for *team*, one per category. Each row
	holds ``category``, ``email_enabled`` and ``in_app_enabled``."""
	user = frappe.session.user
	_require_member(user, team)
	saved = []
	# Serialize preference upserts for this team. The unique constraint remains the
	# final guard when separate requests race.
	frappe.db.get_value("Team", team, "name", for_update=True)
	for pref in preferences:
		category = pref.get("category")
		if category not in CATEGORIES:
			frappe.throw(_("Unsupported notification category {0}.").format(frappe.bold(category)))
		email = bool(frappe.utils.cint(pref.get("email_enabled", 1)))
		in_app = bool(frappe.utils.cint(pref.get("in_app_enabled", 1)))

		doc = UserNotificationPreference.upsert(user, team, category, email, in_app)
		saved.append(
			{"category": category, "email_enabled": email, "in_app_enabled": in_app, "name": doc.name}
		)

	return {"saved": True, "preferences": saved}


@frappe.whitelist()
def get_user_preferences(team: str) -> dict:
	"""Return the calling user's notification preferences for *team*."""
	user = frappe.session.user
	_require_member(user, team)
	rows = frappe.get_all(
		"User Notification Preference",
		filters={"user": user, "team": team},
		fields=["category", "email_enabled", "in_app_enabled"],
	)

	return {"preferences": rows}


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
	"""Raise a Server event from a Pilot. The team and server come from the Pilot's
	credential, never from the body. Billing and Team events are refused, so a compromised bench
	cannot email a whole team."""
	credential = frappe.local.pilot_credential
	team = credential.team
	if frappe.db.get_value("Notification Event Type", event_type, "category") != "Server":
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
