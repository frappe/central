# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
from frappe.utils import escape_html, format_datetime, get_datetime, get_system_timezone, now_datetime

from central.iam import can, is_active_team_member
from central.notification import CATEGORIES
from central.notification.doctype.user_notification_preference.user_notification_preference import (
	UserNotificationPreference,
)
from central.sso import central_url

MAX_ITEMS = 50
SEVERITY_ORDER = {"Error": 0, "Warning": 1, "Success": 2, "Info": 3}
FEED_FIELDS = [
	"category",
	"event_type",
	"severity",
	"required_cap",
	"server",
	"title",
	"message",
	"action_label",
	"action_route",
	"creation",
]


def send_due_digests() -> None:
	"""Email each member whose digest hour is now the feed entries since their last digest."""
	now = now_datetime()
	preferences = frappe.get_all(
		"User Notification Preference",
		filters={"frequency": ["in", ["Daily", "Weekly"]], "email_enabled": 1},
		fields=["name", "user", "team", "category", "frequency", "digest_hour", "last_digest_at"],
		limit=0,
	)
	time_zones = get_time_zones(list({preference.user for preference in preferences}))
	due = defaultdict(list)
	for preference in preferences:
		if is_digest_due(preference, time_zones.get(preference.user), now):
			due[(preference.user, preference.team)].append(preference)

	for (user, team), group in due.items():
		frequency = "Weekly" if all(preference.frequency == "Weekly" for preference in group) else "Daily"
		try:
			since = {preference.category: preference.last_digest_at or now for preference in group}
			send_digest(user, team, since, frequency)
		except Exception:
			# The entries stay after last_digest_at, so the next digest picks them up.
			frappe.log_error(title=f"Notification digest failed: {user}")
			continue
		frappe.db.set_value(
			"User Notification Preference",
			{"name": ["in", [preference.name for preference in group]]},
			"last_digest_at",
			now,
		)


def is_digest_due(preference, time_zone: str | None, now: datetime) -> bool:
	system = ZoneInfo(get_system_timezone())
	try:
		zone = ZoneInfo(time_zone) if time_zone else system
	except ZoneInfoNotFoundError:
		zone = system
	local_now = now.replace(tzinfo=system).astimezone(zone)
	if local_now.hour != preference.digest_hour:
		return False
	return preference.frequency == "Daily" or local_now.weekday() == 0


def send_digest(user: str, team: str, since: dict[str, datetime], frequency: str) -> None:
	"""Send one email with the feed entries of each category created after its time in *since*."""
	if not is_active_team_member(user, team):
		return

	since = {category: get_datetime(value) for category, value in since.items()}
	rows = get_digest_rows(user, team, since)
	if not rows:
		return

	subject, body = _render_digest(team, rows[:MAX_ITEMS], len(rows), frequency, min(since.values()))
	frappe.sendmail(recipients=[user], subject=subject, message=body)


def get_digest_rows(user: str, team: str, since: dict[str, datetime]) -> list:
	"""Feed entries the member can see and still wants by email. Instant-only events are left out."""
	preferences = UserNotificationPreference.load_for_users(team, [user])
	sent_instantly = set(
		frappe.get_all(
			"Notification Event Type",
			or_filters={"is_critical": 1, "direct_recipients": "Affected User"},
			pluck="name",
		)
	)
	rows = frappe.get_all(
		"Team Notification",
		filters={"team": team, "category": ["in", list(since)], "creation": [">", min(since.values())]},
		fields=FEED_FIELDS,
		order_by="creation desc",
		limit=0,
	)

	capabilities = {}
	kept = []
	for row in rows:
		event_emails = preferences.get((user, row.category), {}).get("events", {})
		if row.creation <= since[row.category] or row.event_type in sent_instantly:
			continue
		if not event_emails.get(row.event_type, True):
			continue
		if row.required_cap:
			key = (row.required_cap, row.server)
			if key not in capabilities:
				capabilities[key] = can(user, team, row.required_cap, server=row.server)
			if not capabilities[key]:
				continue
		kept.append(row)

	return sorted(kept, key=_digest_sort_key)


def get_time_zones(users: list[str]) -> dict[str, str]:
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "time_zone"], limit=0)
	return {row.name: row.time_zone for row in rows if row.time_zone}


def _render_digest(
	team: str, rows: list, total: int, frequency: str, period_start: datetime
) -> tuple[str, str]:
	team_name = frappe.db.get_value("Team", team, "team_name") or team
	count = _("1 update") if total == 1 else _("{0} updates").format(total)
	label = _(frequency)
	subject = _("{0} summary for {1}: {2}").format(label, team_name, count)
	groups = [
		{
			"category": escape_html(category),
			"entries": [_digest_item(row) for row in rows if row.category == category],
		}
		for category in CATEGORIES
		if any(row.category == category for row in rows)
	]
	more_count = total - len(rows)
	body = frappe.render_template(
		"templates/emails/notification_digest.html",
		{
			"title": escape_html(_("{0} summary for {1}").format(label, team_name)),
			"subtitle": escape_html(
				_("{0} since {1}").format(count, format_datetime(period_start, "medium"))
			),
			"groups": groups,
			"more_text": escape_html(_("{0} more updates are in your notification feed.").format(more_count))
			if more_count
			else None,
			"preferences_url": escape_html(f"{central_url()}/dashboard/settings/notifications"),
		},
	)
	return subject, body


def _digest_item(row) -> dict:
	parts = [escape_html(part.strip()) for part in (row.message or "").split("\n\n") if part.strip()]
	action_url = None
	if row.action_route:
		route = row.action_route if row.action_route.startswith("/") else f"/{row.action_route}"
		action_url = escape_html(f"{central_url()}/dashboard{route}")

	return {
		"summary": f"[{row.severity}] {escape_html(row.title or row.event_type)}",
		"body_parts": parts,
		"action_label": escape_html(row.action_label) if row.action_label else None,
		"action_url": action_url,
	}


def _digest_sort_key(row) -> tuple:
	index = CATEGORIES.index(row.category) if row.category in CATEGORIES else len(CATEGORIES)
	return (index, SEVERITY_ORDER.get(row.severity, len(SEVERITY_ORDER)), -row.creation.timestamp())
