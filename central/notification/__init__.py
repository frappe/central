# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder import Criterion, Order
from frappe.query_builder.functions import Count

CATEGORIES = ("Billing", "Server", "Team")
SEVERITIES = ("Info", "Success", "Warning", "Error")
# Records that point at one server through their `server` field.
SERVER_LINKED_DOCTYPES = ("Resource Action", "VM Snapshot", "Site", "Site Domain")


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
	server: str | None = None,
	action_label: str | None = None,
	action_route: str | None = None,
	publish: bool = True,
):
	"""Record one in-app notification for a team and nudge the console. Email preferences do
	not apply: a failure belongs in the feed whether or not the team wants an email. The nudge
	carries only the team, so it leaks nothing across sockets."""
	if category not in CATEGORIES:
		frappe.throw(frappe._("Unsupported notification category {0}.").format(frappe.bold(category)))
	if severity not in SEVERITIES:
		frappe.throw(frappe._("Unsupported notification severity {0}.").format(frappe.bold(severity)))

	doc = frappe.get_doc(
		{
			"doctype": "Team Notification",
			"team": team,
			"category": category,
			"event_type": event_type,
			"severity": severity,
			"required_cap": required_cap,
			"title": title,
			"message": message,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"server": server or get_reference_server(reference_doctype, reference_name),
			"action_label": action_label,
			"action_route": action_route,
			"is_read": 0,
		}
	)
	# Team Notification is an internal delivery record and grants no customer create permission.
	doc.insert(ignore_permissions=True)

	if publish:
		from central.notification.engine import publish_team_nudge

		publish_team_nudge(team)

	return doc


def get_reference_server(reference_doctype: str | None, reference_name: str | None) -> str | None:
	"""The server a notification is about, so the feed can hide it from members scoped
	to other servers. None for a team-level subject such as an invoice."""
	if not reference_name:
		return None
	if reference_doctype == "Virtual Machine":
		return reference_name if frappe.db.exists("Virtual Machine", reference_name) else None
	if reference_doctype in SERVER_LINKED_DOCTYPES:
		return frappe.db.get_value(reference_doctype, reference_name, "server") or None

	return None


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
	"""Conditions for the notifications a user may see in a team's feed. The list and the
	unread count share them, so the two never disagree."""
	from central.iam import user_has_operator_bypass

	conds = [tn.team == team]
	if category:
		conds.append(tn.category == category)
	if user_has_operator_bypass(user):
		return conds

	conds.append(_capability_gate(tn, team, user))

	disabled = frappe.get_all(
		"User Notification Preference",
		filters={"user": user, "team": team, "in_app_enabled": 0},
		pluck="category",
	)
	if disabled:
		conds.append(tn.category.notin(disabled))

	return conds


def _capability_gate(tn, team: str, user: str):
	"""A row with no required capability is visible to every member. A team-wide grant
	sees a row it has the capability for. A grant scoped to servers sees a row only when
	the row is about one of those servers."""
	from central.iam import ALL_SERVERS, get_allowed_servers, resolve_user_grants

	gate = tn.required_cap.isnull() | (tn.required_cap == "")
	caps = {cap for grant in resolve_user_grants(user).get(team, []) for cap in grant["caps"]}
	for cap in sorted(caps):
		servers = get_allowed_servers(user, cap)[team]
		if servers == ALL_SERVERS:
			gate = gate | (tn.required_cap == cap)
		else:
			gate = gate | ((tn.required_cap == cap) & tn.server.isin(sorted(servers)))

	return gate


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


def unread_names(team: str, user: str, *, limit: int) -> list[str]:
	"""Return one bounded batch of visible unread notification names."""
	tn = frappe.qb.DocType("Team Notification")
	nr = frappe.qb.DocType("Notification Read")

	return (
		frappe.qb.from_(tn)
		.left_join(nr)
		.on((nr.notification == tn.name) & (nr.user == user))
		.select(tn.name)
		.where(Criterion.all(_visible_conditions(tn, team, user, None)))
		.where(nr.name.isnull())
		.orderby(tn.creation, order=Order.desc)
		.limit(limit)
	).run(pluck=True)


def list_notifications(
	team: str,
	*,
	user: str | None = None,
	start: int = 0,
	limit: int = 50,
	category: str | None = None,
	unread_only: bool = False,
) -> dict:
	"""One page of the team's feed for the user, newest first, with read state. Reads one row
	past ``limit`` to report ``has_next_page`` without a count."""
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
