import base64
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, get_datetime
from frappe.utils.translations import _lt

from central.activity.events import CATEGORIES, SYSTEM_USERS
from central.iam import can, get_user_team_names, user_has_operator_bypass
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.utils.guards import require_capability

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
FIELDS = [
	"name",
	"team",
	"event",
	"category",
	"title",
	"status",
	"details",
	"error",
	"actor",
	"occurred_at",
]


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:view",
	_lt("You can't view this server's activity. Ask a team admin to review your access."),
	server="resource_id",
)
def server_activity(
	team: str | None = None,
	resource_id: str | None = None,
	cursor: str | None = None,
	limit: int = DEFAULT_LIMIT,
	category: str | None = None,
) -> dict:
	"""One server's activity, newest first, after the opaque cursor if given."""
	if not team or not resource_id:
		frappe.throw(_("Select a server to continue."), frappe.ValidationError)

	server = VirtualMachine.get_team_server_name(team, resource_id)
	# Every row that names this server belongs here, including its sites and domains.
	return _activity(team, {"server": server}, cursor, limit, category)


@frappe.whitelist(methods=["GET"])
def team_activity(
	team: str | None = None,
	cursor: str | None = None,
	limit: int = DEFAULT_LIMIT,
	category: str | None = None,
) -> dict:
	"""One team's activity, newest first. The permission rules narrow it to what the reader may see."""
	if not team:
		frappe.throw(_("Select a team to continue."), frappe.ValidationError)
	if not user_has_operator_bypass() and team not in get_user_team_names(frappe.session.user):
		frappe.throw(_("You can't view this team's activity."), frappe.PermissionError)

	return _activity(team, {}, cursor, limit, category)


def _activity(
	team: str,
	filters: dict,
	cursor: str | None,
	limit: int,
	category: str | None,
) -> dict:
	_validate_category(category)
	after = _decode_cursor(cursor) if cursor else None
	page_size = max(1, min(cint(limit) or DEFAULT_LIMIT, MAX_LIMIT))
	page = _page({**filters, "team": team}, category, after, page_size + 1)

	has_more = len(page) > page_size
	rows = page[:page_size]
	include_ip = can(frappe.session.user, team, "team:manage_members")
	events = [_event(row) for row in rows]
	if include_ip:
		_add_ips(events, team)
	_label_actors(events)

	return {
		"events": events,
		"next_cursor": _encode_cursor(events[-1]) if has_more and events else None,
	}


def _page(filters: dict, category: str | None, after: dict | None, size: int) -> list[dict]:
	rows: list[dict] = []
	if category:
		filters = {**filters, "category": category}
	for group in _cursor_queries(after):
		rows.extend(
			frappe.get_list(
				"Activity Event",
				filters={**filters, **group},
				fields=FIELDS,
				order_by="occurred_at desc, name desc",
				limit=size,
			)
		)

	rows.sort(key=lambda row: (str(row.occurred_at), row.name), reverse=True)
	return rows[:size]


def _cursor_queries(after: dict | None) -> list[dict]:
	if not after:
		return [{}]

	return [
		{"occurred_at": ["<", after["timestamp"]]},
		{"occurred_at": ["=", after["timestamp"]], "name": ["<", after["name"]]},
	]


def _event(row) -> dict[str, Any]:
	return {
		"id": row.name,
		"event": row.event,
		"category": row.category,
		"occurred_at": str(row.occurred_at),
		"actor": row.actor,
		"title": _(row.title),
		"status": row.status or None,
		"details": _details(row.details),
		"error": row.error or None,
	}


def _add_ips(events: list[dict], team: str) -> None:
	if not events:
		return

	# The endpoint checked team:manage_members before this system read. The address
	# table has no customer permission, so a direct DocType read cannot return it.
	addresses = frappe.get_all(
		"Activity Event IP",
		filters={"event": ("in", [event["id"] for event in events]), "team": team},
		fields=["event", "ip_address"],
	)
	by_event = {row.event: row.ip_address for row in addresses}
	for event in events:
		if ip_address := by_event.get(event["id"]):
			event["ip_address"] = ip_address


def _details(raw) -> list[dict]:
	parsed = frappe.parse_json(raw or "[]")
	if not isinstance(parsed, list):
		return []
	return [
		{
			"label": _(detail["label"]),
			"from": None if detail.get("from") is None else str(detail["from"]),
			"to": None if detail.get("to") is None else str(detail["to"]),
		}
		for detail in parsed
		if isinstance(detail, dict) and "label" in detail
	]


def _label_actors(events: list[dict]) -> None:
	emails = {event["actor"] for event in events if event["actor"] not in SYSTEM_USERS}
	labels = _user_labels(emails)
	for event in events:
		event["actor"] = _actor(event["actor"], labels)


def _user_labels(emails: set[str]) -> dict[str, tuple]:
	if not emails:
		return {}

	# User grants no read to a customer, and the event already names the actor. Read the
	# display fields directly; a missing row falls back to the email in `_actor`.
	return {
		row.name: (row.full_name, row.user_image)
		for row in frappe.db.get_values(
			"User",
			{"name": ("in", list(emails))},
			["name", "full_name", "user_image"],
			as_dict=True,
		)
	}


def _actor(email: str, labels: dict[str, tuple]) -> dict:
	if email in SYSTEM_USERS:
		return {"label": _("System"), "kind": "system", "image": None}
	if user_has_operator_bypass(email):
		return {"label": _("Frappe Cloud"), "kind": "system", "image": None}

	name, image = labels.get(email, (email, None))
	return {"label": name or email, "kind": "user", "image": image or None}


def _validate_category(category: str | None) -> None:
	if category and category not in CATEGORIES:
		frappe.throw(
			_("Filter activity by action, configuration, snapshot, site, team, member or access."),
			frappe.ValidationError,
		)


def _encode_cursor(event: dict) -> str:
	payload = {"t": event["occurred_at"], "n": event["id"]}
	raw = json.dumps(payload, separators=(",", ":")).encode()
	return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict:
	try:
		if len(cursor) > 512:
			raise ValueError
		decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
		payload = json.loads(decoded)
		if (
			not isinstance(payload, dict)
			or not isinstance(payload.get("t"), str)
			or not isinstance(payload.get("n"), str)
			or not payload["t"]
			or not payload["n"]
		):
			raise ValueError
		get_datetime(payload["t"])
	except Exception:
		frappe.throw(
			_("This activity cursor is not valid. Reload the activity feed."),
			frappe.ValidationError,
		)
	return {"timestamp": payload["t"], "name": payload["n"]}
