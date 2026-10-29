import hashlib
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, cint, now_datetime

from central.activity.events import SYSTEM_USERS, EventType, get_event

MAX_EVENT_KEY_LENGTH = 140


class ActivityEvent(Document):
	"""One customer-visible event on a team resource, appended once and never rewritten."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actor: DF.Link | None
		category: DF.Literal["action", "configuration", "snapshot", "site", "team", "member", "access"]
		details: DF.JSON | None
		error: DF.SmallText | None
		event: DF.Data
		event_key: DF.Data
		occurred_at: DF.Datetime
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		required_capability: DF.Link
		resource_name: DF.DynamicLink
		resource_type: DF.Link
		server: DF.Link | None
		status: DF.Data | None
		team: DF.Link
		title: DF.Data
	# end: auto-generated types

	@staticmethod
	def record(
		event: str,
		*,
		resource_type: str,
		resource_name: str,
		key: str,
		actor: str | None = None,
		occurred_at=None,
		status: str | None = None,
		details: list[dict[str, Any]] | None = None,
		error: str | None = None,
		reference: tuple[str, str] | None = None,
	) -> str | None:
		"""Record `event` on a resource once per `key`. Team, server, capability and IP are
		derived here, so a caller cannot widen who sees the row."""
		event_type = get_event(event)
		event_key = _event_key(event, key)
		ip_address = _request_ip(actor or frappe.session.user)

		try:
			team, server = get_resource_scope(resource_type, resource_name)
			if not team or frappe.db.exists("Activity Event", {"event_key": event_key}):
				return None

			doc = frappe.get_doc(
				_values(
					event=event,
					event_type=event_type,
					event_key=event_key,
					team=team,
					server=server,
					resource_type=resource_type,
					resource_name=resource_name,
					actor=actor,
					occurred_at=occurred_at,
					status=status,
					details=details,
					error=error,
					reference=reference,
				)
			)
			# The system writes the ledger on behalf of any caller; a departed actor must still land.
			try:
				doc.insert(ignore_permissions=True, ignore_links=True)
			except frappe.UniqueValidationError:
				# Two workers can record the same key at once; the first row is the event.
				return None
		except Exception:
			# An audit row must never roll back the operation it describes.
			frappe.log_error(title="Activity event not recorded", message=frappe.get_traceback())
			return None

		if ip_address:
			_record_ip(doc, ip_address)

		try:
			_publish(team)
		except Exception:
			frappe.log_error(title="Activity event not published", message=frappe.get_traceback())

		return doc.name

	@staticmethod
	def clear_old_logs(days: int = 30) -> None:
		"""Log Settings calls this daily with the days an operator keeps."""
		cutoff = add_days(now_datetime(), -cint(days))
		addresses = frappe.qb.DocType("Activity Event IP")
		frappe.db.delete(addresses, filters=addresses.occurred_at < cutoff)
		events = frappe.qb.DocType("Activity Event")
		frappe.db.delete(events, filters=events.occurred_at < cutoff)


def _event_key(event: str, key: str) -> str:
	value = f"{event}:{key}"
	if len(value) <= MAX_EVENT_KEY_LENGTH:
		return value

	# A team name plus a member email can exceed the Data column; the digest keeps dedupe.
	return f"{event}:{hashlib.sha256(value.encode()).hexdigest()}"[:MAX_EVENT_KEY_LENGTH]


def _values(
	*,
	event: str,
	event_type: EventType,
	event_key: str,
	team: str,
	server: str | None,
	resource_type: str,
	resource_name: str,
	actor: str | None,
	occurred_at,
	status: str | None,
	details: list[dict[str, Any]] | None,
	error: str | None,
	reference: tuple[str, str] | None,
) -> dict[str, Any]:
	actor = actor or frappe.session.user
	return {
		"doctype": "Activity Event",
		"team": team,
		"resource_type": resource_type,
		"resource_name": resource_name,
		"server": server,
		"event": event,
		"category": event_type.category,
		"title": event_type.title,
		"required_capability": event_type.capability,
		"status": status,
		"actor": actor,
		"occurred_at": occurred_at or now_datetime(),
		"details": frappe.as_json(details) if details else None,
		"error": error,
		"reference_doctype": reference[0] if reference else None,
		"reference_name": reference[1] if reference else None,
		"event_key": event_key,
	}


def _record_ip(event, ip_address: str) -> None:
	# The address sits in an operator-only table, so a customer read of the event
	# cannot return it. A failure must not discard the event above.
	try:
		frappe.get_doc(
			{
				"doctype": "Activity Event IP",
				"event": event.name,
				"team": event.team,
				"ip_address": ip_address,
				"occurred_at": event.occurred_at,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="Activity event IP not recorded", message=frappe.get_traceback())


def _request_ip(actor: str) -> str | None:
	# A background job or a different actor has no request IP of its own.
	if actor in SYSTEM_USERS or actor != frappe.session.user:
		return None

	return getattr(frappe.local, "request_ip", None)


def _publish(team: str) -> None:
	# A patch writes history, and only the API and the console need a live update.
	if frappe.flags.in_patch:
		return

	# The team room includes every member, so the signal carries no resource identity.
	frappe.publish_realtime(
		"activity_changed",
		{},
		doctype="Team",
		docname=team,
		after_commit=True,
	)


def get_resource_scope(resource_type: str, resource_name: str) -> tuple[str | None, str | None]:
	"""The owning team, and the server whose scoped grants also see the event."""
	if resource_type == "Team":
		return resource_name, None

	meta = frappe.get_meta(resource_type)
	fields = [name for name in ("team", "server") if meta.has_field(name)]
	row = frappe.db.get_value(resource_type, resource_name, fields, as_dict=True) if fields else None
	if not row:
		return None, None

	server = resource_name if resource_type == "Virtual Machine" else row.get("server")
	return row.get("team"), server


def on_doctype_update() -> None:
	"""Index the feed's paging order."""
	frappe.db.add_index("Activity Event", ["server", "occurred_at", "name"])
	frappe.db.add_index("Activity Event", ["resource_type", "resource_name", "occurred_at", "name"])
	frappe.db.add_index("Activity Event", ["team", "occurred_at", "name"])
	frappe.db.add_index("Activity Event", ["team", "required_capability", "occurred_at"])
