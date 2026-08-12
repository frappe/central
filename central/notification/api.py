# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification dashboard API — customer-facing endpoints for preferences and events."""

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.iam import is_active_team_member, resolve_team, user_has_operator_bypass


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
	"""Create or update the calling user's notification preferences for *team*.

	``preferences`` is a list of dicts, each with:
	  - ``category``: Billing | Server | Team
	  - ``email_enabled``: 0 | 1
	  - ``in_app_enabled``: 0 | 1

	Upserts per (user, team, category). Returns the saved preferences."""
	user = frappe.session.user
	_require_member(user, team)
	saved = []
	for pref in preferences:
		category = pref.get("category")
		if not category:
			continue
		email = bool(frappe.utils.cint(pref.get("email_enabled", 1)))
		in_app = bool(frappe.utils.cint(pref.get("in_app_enabled", 1)))

		existing = frappe.db.get_value(
			"User Notification Preference",
			{"user": user, "team": team, "category": category},
			"name",
		)
		if existing:
			frappe.db.set_value(
				"User Notification Preference",
				existing,
				{"email_enabled": int(email), "in_app_enabled": int(in_app)},
			)
			name = existing
		else:
			doc = frappe.get_doc(
				{
					"doctype": "User Notification Preference",
					"user": user,
					"team": team,
					"category": category,
					"email_enabled": int(email),
					"in_app_enabled": int(in_app),
				}
			).insert(ignore_permissions=True)
			name = doc.name

		saved.append({"category": category, "email_enabled": email, "in_app_enabled": in_app, "name": name})

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
	"""Inbound event from a Pilot instance (authenticated via X-Pilot-Token).

	Delegates to the notification engine. The team is resolved from the
	authenticated pilot credential — never from the request body.

	A pilot may only raise Server-domain events (the infra events a bench observes).
	Billing/Team event types are Central-originated, so refusing them here stops a
	compromised or buggy bench from fanning out, e.g., a payment_failure email to the
	whole team. An unknown event type has no category and is refused too.
	"""
	team = frappe.local.pilot_credential.team
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
	)


# ── In-app notification feed ─────────────────────────────────────────────────
# The team's unified feed (Team Notification) across billing and server events.
# Moved here from billing so the reader lives with the notification domain; billing
# only imports the writer. Gated on team membership + per-row capability, NOT on
# billing:view (which used to hide the whole feed from non-billing members).


@frappe.whitelist()
def list_notifications(
	team: str | None = None,
	start: int = 0,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""One page of the team's in-app notification feed — billing and server events —
	newest first. Returns ``has_next_page`` so the console can page with ``start``.

	Capability-filtered: operators see everything; a member only sees notifications
	whose ``required_cap`` they hold."""
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
		if not frappe.db.exists("Notification Read", {"user": user, "notification": name}):
			frappe.get_doc(
				{
					"doctype": "Notification Read",
					"user": user,
					"notification": name,
					"read_at": frappe.utils.now_datetime(),
				}
			).insert(ignore_permissions=True)
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
	from central.notification import list_notifications as _list

	feed = _list(team, user=frappe.session.user, limit=10000)
	now = frappe.utils.now_datetime()
	updated = 0
	for item in feed["items"]:
		if not item["is_read"] and not frappe.db.exists(
			"Notification Read", {"user": frappe.session.user, "notification": item["name"]}
		):
			frappe.get_doc(
				{
					"doctype": "Notification Read",
					"user": frappe.session.user,
					"notification": item["name"],
					"read_at": now,
				}
			).insert(ignore_permissions=True)
			updated += 1
	return {"ok": True, "updated": updated, "unread": 0}
