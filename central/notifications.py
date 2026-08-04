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
		# Fan out only to active team members: an event name is not an access boundary.
		for user in frappe.get_all("Team Member", filters={"parent": team, "status": "Active"}, pluck="user"):
			frappe.publish_realtime(f"team_notification:{team}", {"team": team}, user=user, after_commit=True)
	return doc


def unread_count(team: str) -> int:
	"""Unread in-app notifications for a team — the bell badge count."""
	return frappe.db.count("Team Notification", {"team": team, "is_read": 0})
