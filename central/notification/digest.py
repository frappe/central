# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from frappe import _
from frappe.utils import escape_html, format_datetime, get_datetime, get_system_timezone, now_datetime

from central.iam import can, is_active_team_member
from central.notification import CATEGORIES
from central.notification.doctype.notification_digest_setting.notification_digest_setting import (
	NotificationDigestSetting,
)
from central.notification.doctype.user_notification_preference.user_notification_preference import (
	UserNotificationPreference,
)
from central.sso import central_url

MAX_ITEMS = 50
MAX_SCAN = 2000
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
	for (user, team), group in _due_groups(now).items():
		_send_group(user, team, group, now)


def _due_groups(now: datetime) -> dict[tuple[str, str], list[frappe._dict]]:
	preferences = frappe.get_all(
		"User Notification Preference",
		filters={"frequency": ["in", ["Daily", "Weekly"]], "email_enabled": 1},
		fields=["name", "user", "team", "category", "frequency", "last_digest_at"],
		limit=0,
	)
	time_zones = get_time_zones(list({preference.user for preference in preferences}))
	digest_hours = _digest_hours(preferences)
	due = defaultdict(list)
	for preference in preferences:
		digest_hour = digest_hours[(preference.user, preference.team)]
		if is_digest_due(preference, time_zones.get(preference.user), digest_hour, now):
			due[(preference.user, preference.team)].append(preference)
	return due


def _digest_hours(preferences: list[frappe._dict]) -> dict[tuple[str, str], int]:
	"""Read each team's digest hours in one query per team, not one query per row."""
	users_by_team = defaultdict(set)
	for preference in preferences:
		users_by_team[preference.team].add(preference.user)

	return {
		(user, team): digest_hour
		for team, users in users_by_team.items()
		for user, digest_hour in NotificationDigestSetting.load_for_users(team, list(users)).items()
	}


def _send_group(user: str, team: str, group: list[frappe._dict], now: datetime) -> None:
	frequency = "Weekly" if all(preference.frequency == "Weekly" for preference in group) else "Daily"
	try:
		since = {preference.category: preference.last_digest_at or now for preference in group}
		send_digest(user, team, since, frequency, until=now)
	except Exception:
		frappe.log_error(title=f"Notification digest failed: {user}")
		return
	frappe.db.set_value(
		"User Notification Preference",
		{"name": ["in", [preference.name for preference in group]]},
		"last_digest_at",
		now,
	)


def _zone_for(time_zone: str | None) -> ZoneInfo:
	if not time_zone:
		return ZoneInfo(get_system_timezone())
	try:
		return ZoneInfo(time_zone)
	except ZoneInfoNotFoundError:
		return ZoneInfo(get_system_timezone())


def _local_datetime(value: datetime, time_zone: str | None) -> datetime:
	system = ZoneInfo(get_system_timezone())
	return value.replace(tzinfo=system).astimezone(_zone_for(time_zone)).replace(tzinfo=None)


def is_digest_due(preference: frappe._dict, time_zone: str | None, digest_hour: int, now: datetime) -> bool:
	"""Whether the first scheduled digest since the last send has passed."""
	system = ZoneInfo(get_system_timezone())
	zone = _zone_for(time_zone)
	local_now = now.replace(tzinfo=system).astimezone(zone)
	if not preference.get("last_digest_at"):
		return True

	last_sent = get_datetime(preference.last_digest_at).replace(tzinfo=system).astimezone(zone)
	due = last_sent.replace(hour=digest_hour, minute=0, second=0, microsecond=0)
	if preference.frequency == "Weekly":
		due += timedelta(days=(0 - last_sent.weekday()) % 7)
		if due <= last_sent:
			due += timedelta(days=7)
	elif due <= last_sent:
		due += timedelta(days=1)

	return local_now >= due


def send_digest(
	user: str, team: str, since: dict[str, datetime], frequency: str, until: datetime | None = None
) -> None:
	"""Send one email with the feed entries of each category created after its time in *since*, up to *until*."""
	if not is_active_team_member(user, team):
		return

	since = {category: get_datetime(value) for category, value in since.items()}
	rows, is_capped = get_digest_rows(user, team, since, until)
	if not rows:
		return

	time_zone = frappe.db.get_value("User", user, "time_zone")
	subject, body = _render_digest(
		team, rows[:MAX_ITEMS], len(rows), is_capped, frequency, min(since.values()), time_zone
	)
	frappe.sendmail(recipients=[user], subject=subject, message=body)


def get_digest_rows(
	user: str, team: str, since: dict[str, datetime], until: datetime | None = None
) -> tuple[list[frappe._dict], bool]:
	"""Feed entries the member can see and still wants by email, and whether a category hit MAX_SCAN."""
	skipped = _events_sent_instantly(user, team)
	rows = []
	is_capped = False
	for category, start in since.items():
		filters = [["team", "=", team], ["category", "=", category], ["creation", ">", start]]
		if until:
			filters.append(["creation", "<=", until])
		# A feed entry need not have an event type. SQL excludes NULL from NOT IN,
		# so keep those entries with an explicit OR.
		or_filters = None
		if skipped:
			or_filters = [["event_type", "is", "not set"], ["event_type", "not in", skipped]]
		scanned = frappe.get_all(
			"Team Notification",
			filters=filters,
			or_filters=or_filters,
			fields=FEED_FIELDS,
			order_by="creation desc",
			limit=MAX_SCAN + 1,
		)
		is_capped = is_capped or len(scanned) > MAX_SCAN
		rows += scanned[:MAX_SCAN]
	return sorted(_visible_rows(user, team, rows), key=_digest_sort_key), is_capped


def _events_sent_instantly(user: str, team: str) -> list[str]:
	preferences = UserNotificationPreference.load_for_users(team, [user])
	muted = [
		event
		for preference in preferences.values()
		for event, is_on in preference["events"].items()
		if not is_on
	]
	sent_at_once = frappe.get_all(
		"Notification Event Type",
		or_filters={"is_critical": 1, "direct_recipients": "Affected User"},
		pluck="name",
	)
	return muted + sent_at_once


def _visible_rows(user: str, team: str, rows: list[frappe._dict]) -> list[frappe._dict]:
	capabilities = {}
	kept = []
	for row in rows:
		if row.required_cap:
			key = (row.required_cap, row.server)
			if key not in capabilities:
				capabilities[key] = can(user, team, row.required_cap, server=row.server)
			if not capabilities[key]:
				continue
		kept.append(row)
	return kept


def get_time_zones(users: list[str]) -> dict[str, str]:
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "time_zone"], limit=0)
	return {row.name: row.time_zone for row in rows if row.time_zone}


def _digest_more_text(more_count: int, is_capped: bool) -> str | None:
	if not more_count:
		return None
	if more_count == 1 and not is_capped:
		return _("1 more update is in your notification feed.")
	return _("{0} more updates are in your notification feed.").format(
		f"{more_count}{'+' if is_capped else ''}"
	)


def _render_digest(
	team: str,
	rows: list[frappe._dict],
	total: int,
	is_capped: bool,
	frequency: str,
	period_start: datetime,
	time_zone: str | None,
) -> tuple[str, str]:
	team_name = frappe.db.get_value("Team", team, "team_name") or team
	plus = "+" if is_capped else ""
	count = _("1 update") if total == 1 and not is_capped else _("{0} updates").format(f"{total}{plus}")
	label = _(frequency)
	subject = _("{0} summary for {1}: {2}").format(label, team_name, count)
	more_text = _digest_more_text(total - len(rows), is_capped)
	# nosemgrep: frappe-ssti -- a fixed template that ships with the app, filled only with escaped values.
	body = frappe.render_template(
		"templates/emails/notification_digest.html",
		{
			"title": escape_html(_("{0} summary for {1}").format(label, team_name)),
			"subtitle": escape_html(
				_("{0} since {1}").format(
					count, format_datetime(_local_datetime(period_start, time_zone), "medium")
				)
			),
			"groups": _digest_groups(rows),
			"more_text": escape_html(more_text) if more_text else None,
			"preferences_url": escape_html(f"{central_url()}/dashboard/settings/notifications"),
		},
	)
	return subject, body


def _digest_groups(rows: list[frappe._dict]) -> list[dict]:
	return [
		{
			"category": escape_html(category),
			"entries": [_digest_item(row) for row in rows if row.category == category],
		}
		for category in CATEGORIES
		if any(row.category == category for row in rows)
	]


def _digest_item(row: frappe._dict) -> dict:
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


def _digest_sort_key(row: frappe._dict) -> tuple:
	index = CATEGORIES.index(row.category) if row.category in CATEGORIES else len(CATEGORIES)
	return (index, SEVERITY_ORDER.get(row.severity, len(SEVERITY_ORDER)), -row.creation.timestamp())
