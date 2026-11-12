import base64
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, convert_utc_to_system_timezone, get_datetime
from frappe.utils.translations import _lt

from central.central.doctype.activity_event.activity_event import ActivityEvent, get_initiators
from central.central.doctype.activity_event.tracked import get_sentence
from central.iam import user_has_operator_bypass
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.utils.guards import require_capability, require_team_member

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
CATEGORIES = ("action", "configuration", "snapshot", "site", "team", "member", "access")
# A job, a schedule or a region report: the sentence names no actor.
NO_ACTOR = {"label": "", "kind": "system", "image": None}


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:view",
	_lt("You can't view this server's activity. Ask a team admin to review your access."),
	server="resource_id",
)
def server_activity(
	team: str,
	resource_id: str,
	cursor: str | None = None,
	limit: int = DEFAULT_LIMIT,
	category: str | None = None,
	since: str | None = None,
	until: str | None = None,
) -> dict:
	"""One server's activity, including its sites, domains and snapshots, newest first."""
	server = VirtualMachine.get_team_server_name(team, resource_id)
	return get_activity(team, cursor, limit, category, since, until, server=server)


@frappe.whitelist(methods=["GET"])
@require_team_member
def team_activity(
	team: str,
	cursor: str | None = None,
	limit: int = DEFAULT_LIMIT,
	category: str | None = None,
	since: str | None = None,
	until: str | None = None,
) -> dict:
	"""The team's activity, newest first. Each member sees the events their capabilities allow."""
	return get_activity(team, cursor, limit, category, since, until)


def get_activity(
	team: str,
	cursor: str | None,
	limit: int,
	category: str | None,
	since: str | None,
	until: str | None,
	server: str | None = None,
) -> dict:
	if category and category not in CATEGORIES:
		frappe.throw(_("Choose a valid activity type."), frappe.ValidationError)

	page_size = max(1, min(cint(limit) or DEFAULT_LIMIT, MAX_LIMIT))
	rows = ActivityEvent.get_page(
		team,
		limit=page_size + 1,
		server=server,
		category=category,
		since=_parse_instant(since),
		until=_parse_instant(until),
		after=_decode_cursor(cursor) if cursor else None,
	)
	page = rows[:page_size]
	initiators = get_initiators(page)
	actors = _get_actors({row.actor for row in page} | set(initiators.values()))

	return {
		"events": [_to_event(row, actors, initiators.get(row.name)) for row in page],
		"next_cursor": _encode_cursor(page[-1]) if len(rows) > page_size else None,
	}


def _to_event(row, actors: dict[str, dict], initiator: str | None) -> dict:
	return {
		"id": row.name,
		"event": row.event,
		"category": row.category,
		"occurred_at": str(row.creation),
		"actor": actors.get(row.actor, NO_ACTOR),
		"sentence": _(get_sentence(row.event, has_actor=bool(row.actor))),
		"initiator": actors[initiator] if initiator else None,
		"resource": {"type": row.resource_type, "name": row.resource_name, "label": row.resource_label},
		"status": row.status or None,
		"details": [
			{**detail, "label": _(detail["label"])} for detail in frappe.parse_json(row.details or "[]")
		],
		"error": row.error or None,
	}


def _actor_entry(user, is_operator_reader: bool) -> dict:
	if not is_operator_reader and user_has_operator_bypass(user.name):
		return {"label": _("Frappe Cloud"), "kind": "system", "image": None}
	return {
		"label": user.full_name or user.name,
		"kind": "user",
		"image": user.user_image,
	}


def _get_actors(emails: set[str | None]) -> dict[str, dict]:
	"""Operators read as Frappe Cloud to customers and by name to other operators. Members read
	by name. A deleted user keeps their email."""
	people = [email for email in emails if email]
	is_operator_reader = user_has_operator_bypass(frappe.session.user)
	# User grants customers no read, and the event already names the actor.
	users = frappe.db.get_values(
		"User", {"name": ("in", people or [""])}, ["name", "full_name", "user_image"], as_dict=True
	)
	actors = {email: {"label": email, "kind": "user", "image": None} for email in people}
	for user in users:
		actors[user.name] = _actor_entry(user, is_operator_reader)

	return actors


def _parse_instant(value: str | None) -> datetime | None:
	"""A UTC instant from the browser as the site's naive clock, which `creation` uses."""
	if not value:
		return None

	try:
		return convert_utc_to_system_timezone(get_datetime(value)).replace(tzinfo=None)
	except ValueError:
		frappe.throw(_("Choose a valid date range."), frappe.ValidationError)


def _encode_cursor(row) -> str:
	return base64.urlsafe_b64encode(f"{row.creation}|{row.name}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
	try:
		created, name = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
		get_datetime(created)
	except ValueError:
		frappe.throw(_("Reload the activity feed to continue."), frappe.ValidationError)

	return created, name
