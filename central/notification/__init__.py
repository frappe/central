# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The team-facing in-app notification feed — the console's unified inbox.

One writer, ``create_notification``, records a ``Team Notification`` and nudges the
console over realtime so the bell badge updates live. Every subsystem (billing,
server/infra) funnels through here, so the feed is one queryable source of truth —
distinct from *email* delivery (billing's ``platform.notifications``, which records a
``Billing Notification Log`` and honours the team's email preferences).

An in-app notification is NOT gated by email preferences: a failure or warning
belongs in the dashboard regardless of whether the team wants an email about it.

Read state is per-user: each member tracks which notifications they have read via
the ``Notification Read`` doctype rather than mutating the shared ``is_read`` flag
on ``Team Notification``.
"""

import frappe
from frappe.query_builder import Criterion, Order
from frappe.query_builder.functions import Count

CATEGORIES = ("Billing", "Server", "Team")
SEVERITIES = ("Info", "Success", "Warning", "Error")


def create_notification(
	team: str,
	title: str,
	*,
	category: str = "Billing",
	event_type: str | None = None,
	severity: str = "Info",
	required_cap: str | None = None,
	message: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	action_label: str | None = None,
	action_route: str | None = None,
	publish: bool = True,
):
	"""Record one in-app notification for a team and nudge the console.

	Returns the inserted ``Team Notification``. The realtime nudge carries only the
	team (no content), so it never leaks across sockets; the console refetches the
	feed for the active team when it fires.
	"""
	doc = frappe.get_doc(
		{
			"doctype": "Team Notification",
			"team": team,
			"category": category if category in CATEGORIES else "Billing",
			"event_type": event_type,
			"severity": severity if severity in SEVERITIES else "Info",
			"required_cap": required_cap,
			"title": title,
			"message": message,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"action_label": action_label,
			"action_route": action_route,
			"is_read": 0,
		}
	).insert(ignore_permissions=True)

	if publish:
		from central.notification.engine import publish_team_nudge

		publish_team_nudge(team)
	return doc


_FEED_FIELDS = (
	"name",
	"category",
	"event_type",
	"severity",
	"required_cap",
	"title",
	"message",
	"reference_doctype",
	"reference_name",
	"action_label",
	"action_route",
	"creation",
)


def _visible_conditions(tn, team: str, user: str, category: str | None) -> list:
	"""WHERE criteria for the notifications a user may see in a team's feed — shared
	by the list and the unread count so they never disagree: the team, an optional
	category, the per-row capability gate (skipped for operators), and the user's
	in-app category preferences. ``resolve_user_grants`` is request-cached, so the
	cap set costs one join per request, not one per row."""
	from central.iam import resolve_user_grants, user_has_operator_bypass

	conds = [tn.team == team]
	if category:
		conds.append(tn.category == category)
	if user_has_operator_bypass(user):
		return conds

	caps = sorted({cap for grant in resolve_user_grants(user).get(team, []) for cap in grant.get("caps", [])})
	cap_gate = tn.required_cap.isnull() | (tn.required_cap == "")
	if caps:
		cap_gate = cap_gate | tn.required_cap.isin(caps)
	conds.append(cap_gate)

	disabled = frappe.get_all(
		"User Notification Preference",
		filters={"user": user, "team": team, "in_app_enabled": 0},
		pluck="category",
	)
	if disabled:
		conds.append(tn.category.notin(disabled))
	return conds


def unread_count(team: str, *, user: str | None = None) -> int:
	"""Unread in-app notifications for a team, per-user — the bell badge count.

	One indexed COUNT: the visible-notification filter, LEFT JOINed to the per-user
	``Notification Read`` and kept to rows the user hasn't read."""
	user = user or frappe.session.user
	tn = frappe.qb.DocType("Team Notification")
	nr = frappe.qb.DocType("Notification Read")
	return (
		frappe.qb.from_(tn)
		.left_join(nr)
		.on((nr.notification == tn.name) & (nr.user == user))
		.select(Count("*"))
		.where(Criterion.all(_visible_conditions(tn, team, user, None)))
		.where(nr.name.isnull())
	).run()[0][0]


def list_notifications(
	team: str,
	*,
	user: str | None = None,
	start: int = 0,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""One page of the team's notification feed, filtered per-user, newest first.

	One indexed query: the visible-notification filter (team, per-row capability,
	in-app category preference) is pushed into SQL, LEFT JOINed to the per-user
	``Notification Read`` for read state. Operators see everything. Reads one row
	past ``limit`` to report ``has_next_page`` without a second COUNT."""
	user = user or frappe.session.user
	start = max(0, frappe.utils.cint(start))
	limit = max(1, frappe.utils.cint(limit))
	tn = frappe.qb.DocType("Team Notification")
	nr = frappe.qb.DocType("Notification Read")

	query = (
		frappe.qb.from_(tn)
		.left_join(nr)
		.on((nr.notification == tn.name) & (nr.user == user))
		.select(*(getattr(tn, f) for f in _FEED_FIELDS), nr.name.as_("_read_marker"))
		.where(Criterion.all(_visible_conditions(tn, team, user, category)))
		.orderby(tn.creation, order=Order.desc)
		.limit(limit + 1)
		.offset(start)
	)
	if frappe.utils.cint(unread_only):
		query = query.where(nr.name.isnull())

	items = query.run(as_dict=True)
	has_next_page = len(items) > limit
	items = items[:limit]
	for row in items:
		row["is_read"] = 1 if row.pop("_read_marker", None) else 0

	return {
		"items": items,
		"unread": unread_count(team, user=user),
		"has_next_page": has_next_page,
	}
