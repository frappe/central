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
from frappe import _

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
		frappe.publish_realtime(f"team_notification:{team}", {"team": team}, after_commit=True)
	return doc


def _read_notification_names(team: str, user: str) -> set[str]:
	"""Return the set of notification names the user has read for *team*."""
	return set(
		frappe.get_all(
			"Notification Read",
			filters={"user": user},
			fields=["notification"],
			pluck="notification",
		)
	)


def _unread_notifications(team: str, user: str) -> list[str]:
	"""Return notification names the user has NOT read (capability-filtered)."""
	from central.iam import can, user_has_operator_bypass

	read_names = _read_notification_names(team, user)
	filters = {"team": team}

	rows = frappe.get_all(
		"Team Notification",
		filters=filters,
		fields=["name", "category", "required_cap"],
	)

	if not user_has_operator_bypass(user):
		rows = [row for row in rows if not row.required_cap or can(user, team, row.required_cap)]

	if rows:
		categories = {row.category for row in rows}
		disabled_categories = set(
			frappe.db.get_all(
				"User Notification Preference",
				filters={
					"user": user,
					"team": team,
					"in_app_enabled": 0,
					"category": ["in", list(categories)],
				},
				pluck="category",
			)
		)
		rows = [row for row in rows if row.category not in disabled_categories]

	return [row.name for row in rows if row.name not in read_names]


def unread_count(team: str, *, user: str | None = None) -> int:
	"""Unread in-app notifications for a team, per-user — the bell badge count.

	Read state is per-user via ``Notification Read``.
	"""
	user = user or frappe.session.user
	return len(_unread_notifications(team, user))


def list_notifications(
	team: str,
	*,
	user: str | None = None,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""The team's notification feed, filtered per-user.

	Only notifications whose ``required_cap`` the user possesses (or which
	have no ``required_cap``) are returned.  Operators see everything.

	Read state is per-user (``Notification Read``), not the team-global
	``is_read`` flag.
	"""
	from central.iam import can, user_has_operator_bypass

	user = user or frappe.session.user
	filters = {"team": team}
	if category:
		filters["category"] = category

	items = frappe.get_all(
		"Team Notification",
		filters=filters,
		fields=[
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
		],
		order_by="creation desc",
		limit=frappe.utils.cint(limit) * 3,
	)

	is_operator = user_has_operator_bypass(user)
	if not is_operator:
		items = [row for row in items if not row.required_cap or can(user, team, row.required_cap)]

		categories = {row.category for row in items}
		if categories:
			disabled_categories = set(
				frappe.db.get_all(
					"User Notification Preference",
					filters={
						"user": user,
						"team": team,
						"in_app_enabled": 0,
						"category": ["in", list(categories)],
					},
					pluck="category",
				)
			)
			items = [row for row in items if row.category not in disabled_categories]

	read_names = _read_notification_names(team, user)
	for row in items:
		row["is_read"] = 1 if row.name in read_names else 0

	if frappe.utils.cint(unread_only):
		items = [row for row in items if row.name not in read_names]

	return {
		"items": items[: frappe.utils.cint(limit)],
		"unread": unread_count(team, user=user),
	}
