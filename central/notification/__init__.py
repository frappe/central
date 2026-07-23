# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The team-facing in-app notification feed — the console's unified inbox.

One writer, `create_notification`, records a `Team Notification` and nudges the
console over realtime so the bell badge updates live. Every subsystem (billing,
server/infra) funnels through here, so the feed is one queryable source of truth —
distinct from *email* delivery (billing's `platform.notifications`, which records a
`Billing Notification Log` and honours the team's email preferences).

An in-app notification is NOT gated by email preferences: a failure or warning
belongs in the dashboard regardless of whether the team wants an email about it.
"""

import frappe

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

	Returns the inserted `Team Notification`. The realtime nudge carries only the
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
		# Team-namespaced event so a member's socket only hears its own team's nudge.
		frappe.publish_realtime(
			f"team_notification:{team}", {"team": team}, after_commit=True
		)
	return doc


def unread_count(team: str) -> int:
	"""Unread in-app notifications for a team — the bell badge count."""
	return frappe.db.count("Team Notification", {"team": team, "is_read": 0})


def list_notifications(
	team: str,
	*,
	user: str | None = None,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""The team's notification feed, filtered by the user's capabilities.

	Only notifications whose ``required_cap`` the user possesses (or which
	have no ``required_cap``) are returned.  Operators see everything.
	"""
	from central.iam import can, user_has_operator_bypass

	user = user or frappe.session.user
	filters = {"team": team}
	if category:
		filters["category"] = category
	if frappe.utils.cint(unread_only):
		filters["is_read"] = 0

	items = frappe.get_all(
		"Team Notification",
		filters=filters,
		fields=["name", "category", "event_type", "severity", "required_cap",
				"title", "message", "reference_doctype", "reference_name",
				"action_label", "action_route", "is_read", "read_at", "creation"],
		order_by="creation desc",
		limit=frappe.utils.cint(limit) * 3,  # over-fetch then filter
	)

	is_operator = user_has_operator_bypass(user)
	if not is_operator:
		items = [
			row for row in items
			if not row.required_cap or can(user, team, row.required_cap)
		]

		# Filter out notifications where the user has disabled in-app for the category.
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

	return {
		"items": items[: frappe.utils.cint(limit)],
		"unread": unread_count(team),
	}
