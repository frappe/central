import hashlib
from datetime import datetime
from functools import partial
from typing import Any

import frappe
from frappe.model.document import Document
from frappe.query_builder import Order
from frappe.utils import add_days, cint, now_datetime

from central.central.doctype.activity_event.tracked import ACTION_EVENTS, TRACKED, EventKind, Tracked
from central.iam import get_capability_gate, user_has_operator_bypass

MAX_VALUE_LENGTH = 120
# A long or structured value reads as "changed", not as two values side by side.
SUMMARY_FIELDTYPES = {"Attach", "Attach Image", "Code", "JSON", "Long Text", "Small Text", "Text"}
ACTION = EventKind("", "action", "server:view")
FEED_FIELDS = (
	"name",
	"event",
	"category",
	"resource_type",
	"resource_name",
	"resource_label",
	"status",
	"details",
	"error",
	"actor",
	"creation",
)
FEED_CACHE = "activity_feed"


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
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		required_capability: DF.Link
		resource_label: DF.Data | None
		resource_name: DF.DynamicLink
		resource_type: DF.Link
		server: DF.Link | None
		status: DF.Data | None
		team: DF.Link
	# end: auto-generated types

	@staticmethod
	def record(resource: Document, event: str, kind: EventKind, **values) -> None:
		"""Append one event about `resource`, such as support opening a team."""
		ActivityEvent.insert_events([get_event(resource, event, kind, **values)])

	@staticmethod
	def record_action(action: Document) -> None:
		"""Record the end state of a server action on its server."""
		if action.server and action.action in ACTION_EVENTS:
			server = frappe.get_doc("Virtual Machine", action.server)
			ActivityEvent.insert_events([get_action_event(action, server)])

	@staticmethod
	def insert_events(events: list[dict | None]) -> None:
		"""Write live events. Each team's feed cache clears, and its members hear of it, once
		the change commits."""
		events = [event for event in events if event]
		for event in events:
			# The system writes the ledger for every user. Customers read it through the activity API.
			# An event can describe a resource that is already deleted, so links are not checked.
			frappe.get_doc({"doctype": "Activity Event", **event}).insert(
				ignore_permissions=True, ignore_links=True
			)

		for team in {event["team"] for event in events}:
			clear_feed_cache(team)
			# A reader between now and the commit can cache the old page, so clear again after it.
			frappe.db.after_commit.add(partial(clear_feed_cache, team))
			# The team room includes every member, so the signal carries no event detail.
			frappe.publish_realtime("activity_changed", {}, doctype="Team", docname=team, after_commit=True)

	@staticmethod
	def get_page(
		team: str,
		*,
		limit: int,
		server: str | None = None,
		category: str | None = None,
		since: datetime | None = None,
		until: datetime | None = None,
		after: tuple[str, str] | None = None,
	) -> list[dict]:
		"""Newest first, the events of `team` the session user may see. `after` is the
		(creation, name) of the last event on the previous page."""
		table = frappe.qb.DocType("Activity Event")
		query = (
			frappe.qb.from_(table)
			.select(*FEED_FIELDS)
			.where(table.team == team)
			.orderby(table.creation, order=Order.desc)
			.orderby(table.name, order=Order.desc)
			.limit(limit)
		)
		user = frappe.session.user
		if not user_has_operator_bypass(user):
			query = query.where(get_capability_gate(table.required_capability, table.server, team, user))
		if server:
			query = query.where(table.server == server)
		if category:
			query = query.where(table.category == category)
		if since:
			query = query.where(table.creation >= since)
		if until:
			query = query.where(table.creation < until)
		if after:
			created, name = after
			query = query.where(
				(table.creation < created) | ((table.creation == created) & (table.name < name))
			)

		# The SQL names the reader's grants, filters and cursor, so equal SQL means an equal page.
		key = hashlib.sha256(str(query).encode()).hexdigest()
		return frappe.cache.hget(f"{FEED_CACHE}|{team}", key, generator=lambda: query.run(as_dict=True))

	@staticmethod
	def clear_old_logs(days: int) -> None:
		"""Log Settings calls this daily with the days an operator keeps."""
		table = frappe.qb.DocType("Activity Event")
		frappe.db.delete(table, filters=table.creation < add_days(now_datetime(), -cint(days)))
		frappe.cache.delete_keys(f"{FEED_CACHE}|")


def get_retention_days() -> int:
	"""Log Settings owns how long the feed keeps events. Frappe adds its row after the first
	migrate's patches, so until then the default in hooks applies, as Frappe itself would."""
	days = frappe.db.get_value(
		"Logs To Clear", {"parent": "Log Settings", "ref_doctype": "Activity Event"}, "days"
	)
	return cint(days) or cint(frappe.get_hooks("default_log_clearing_doctypes")["Activity Event"][-1])


def clear_feed_cache(team: str) -> None:
	frappe.cache.delete_value(f"{FEED_CACHE}|{team}")


def record_version(version: Document, method: str | None = None) -> None:
	"""Version.after_insert. A patch that saves documents is not customer activity."""
	spec = TRACKED.get(version.ref_doctype)
	if not spec or frappe.flags.in_patch or frappe.flags.in_install:
		return

	diff = frappe.parse_json(version.data)
	if has_tracked_change(spec, diff):
		resource = frappe.get_doc(version.ref_doctype, version.docname)
		ActivityEvent.insert_events(get_version_events(version, resource, diff))


def record_created(doc: Document, method: str | None = None) -> None:
	"""after_insert of a tracked DocType."""
	if not frappe.flags.in_patch:
		ActivityEvent.insert_events([get_lifecycle_event(doc, "created", doc.owner)])


def record_deleted(doc: Document, method: str | None = None) -> None:
	"""on_trash of a tracked DocType. It runs after the controller checks, so a refused
	delete records nothing."""
	if not frappe.flags.in_patch:
		ActivityEvent.insert_events([get_lifecycle_event(doc, "deleted", frappe.session.user)])


def get_event(
	resource: Document,
	event: str,
	kind: EventKind,
	*,
	actor: str | None = None,
	label: str | None = None,
	details: list[dict] | None = None,
	status: str | None = None,
	error: str | None = None,
	reference: tuple[str, str] | None = None,
	occurred_at: datetime | None = None,
) -> dict | None:
	"""The row for one event about `resource`. The team and server come from the resource, so
	a caller cannot widen who sees it. Frappe keeps `occurred_at` as the creation only in a
	patch, which replays history; a live event happens now."""
	team = resource.name if resource.doctype == "Team" else resource.get("team")
	if not team:
		return None

	spec = TRACKED.get(resource.doctype)
	label_field = (spec and spec.label_field) or resource.meta.title_field or "name"
	return {
		"team": team,
		"server": resource.name if resource.doctype == "Virtual Machine" else resource.get("server"),
		"resource_type": resource.doctype,
		"resource_name": resource.name,
		"resource_label": label or resource.get(label_field) or resource.name,
		"event": event,
		"category": kind.category,
		"required_capability": kind.capability,
		"actor": get_actor(resource, actor or frappe.session.user),
		"status": status,
		"details": frappe.as_json(details) if details else None,
		"error": error,
		"reference_doctype": reference[0] if reference else None,
		"reference_name": reference[1] if reference else None,
		"creation": occurred_at,
	}


def get_actor(resource: Document, actor: str) -> str | None:
	"""The person behind an event, or None for a job, a schedule or a region report. A guest
	session acts for the person the record names, such as the owner signing up."""
	spec = TRACKED.get(resource.doctype)
	if actor == "Guest" and spec and spec.guest_actor:
		return spec.guest_actor(resource) or None

	# Frappe's standard users run jobs, schedules and unsigned requests, not people.
	return None if actor in frappe.STANDARD_USERS else actor


def get_version_events(version, resource: Document, diff: dict) -> list[dict | None]:
	"""The events in the tracked fields of one Version, one per capability."""
	spec = TRACKED[version.ref_doctype]
	context = {
		"actor": version.owner,
		"reference": ("Version", version.name),
		"occurred_at": version.creation,
	}
	events = [
		get_event(resource, f"{spec.prefix}.{kind.verb}", kind, details=details, **context)
		for kind, details in get_changes(spec, resource, diff).items()
	]
	events += get_row_events(spec, resource, diff, context)
	if status := get_new_status(spec, diff):
		event = f"{spec.prefix}.{status.lower()}"
		events.append(get_event(resource, event, spec.get_kind(), status=status, **context))

	return events


def get_row_events(spec: Tracked, resource: Document, diff: dict, context: dict) -> list[dict | None]:
	"""One event per person whose rows changed, such as a member added or given a new role."""
	events = []
	for table in sorted(get_changed_fields(diff) & spec.row_subjects.keys()):
		kind = spec.get_kind(table)
		subject = spec.row_subjects[table]
		subject_doctype = frappe.get_meta(resource.meta.get_field(table).options).get_field(subject).options
		before, after = get_row_sides(resource, table, diff)
		for person in sorted({row.get(subject) for row in before + after} - {None}):
			old = [row for row in before if row.get(subject) == person]
			new = [row for row in after if row.get(subject) == person]
			# A guest session can only add its own person, as when an invitee signs up.
			is_self = context["actor"] in (person, "Guest")
			verb = get_row_verb(bool(old), bool(new), is_self)
			details = [
				get_detail(
					spec.fields[table],
					get_row_labels(spec, resource, table, old),
					get_row_labels(spec, resource, table, new),
				)
			]
			label = get_link_title(subject_doctype, person)
			events.append(
				get_event(
					resource,
					f"{spec.prefix}.{kind.verb}_{verb}",
					kind,
					label=label,
					details=details,
					**{**context, "actor": person if is_self else context["actor"]},
				)
			)

	return events


def get_row_verb(had_rows: bool, has_rows: bool, is_self: bool) -> str:
	if not had_rows:
		return "joined" if is_self else "added"
	if not has_rows:
		return "left" if is_self else "removed"
	return "changed"


def get_lifecycle_event(
	doc: Document, verb: str, actor: str, occurred_at: datetime | None = None
) -> dict | None:
	spec = TRACKED[doc.doctype]
	if not spec.lifecycle:
		return None

	return get_event(doc, f"{spec.prefix}.{verb}", spec.get_kind(), actor=actor, occurred_at=occurred_at)


def get_action_event(action: Document, server: Document) -> dict | None:
	succeeded, failed = ACTION_EVENTS[action.action]
	return get_event(
		server,
		succeeded if action.status == "Succeeded" else failed,
		ACTION,
		actor=action.requested_by,
		details=get_action_details(action),
		status=action.status,
		error=action.error_message,
		reference=("Resource Action", action.name),
		occurred_at=action.completed_at,
	)


def has_tracked_change(spec: Tracked, diff: dict) -> bool:
	return bool(get_new_status(spec, diff) or get_changed_fields(diff) & spec.fields.keys())


def get_new_status(spec: Tracked, diff: dict) -> str | None:
	for fieldname, _old, new in diff.get("changed") or []:
		if fieldname == "status" and new in spec.statuses:
			return new

	return None


def get_changed_fields(diff: dict) -> set[str]:
	changed = {row[0] for row in diff.get("changed") or []}
	tables = {row[0] for key in ("added", "removed", "row_changed") for row in diff.get(key) or []}
	return changed | tables


def get_changes(spec: Tracked, resource: Document, diff: dict) -> dict[EventKind, list[dict]]:
	"""The tracked details of one Version, grouped by the event each belongs to."""
	changes: dict[EventKind, list[dict]] = {}
	for fieldname, old, new in diff.get("changed") or []:
		if fieldname in spec.fields:
			detail = get_field_detail(spec, resource, fieldname, old, new)
			changes.setdefault(spec.get_kind(fieldname), []).append(detail)

	for table in sorted(get_changed_fields(diff) & spec.row_fields.keys() - spec.row_subjects.keys()):
		detail = get_table_detail(spec, resource, table, diff)
		changes.setdefault(spec.get_kind(table), []).append(detail)

	return changes


def get_field_detail(spec: Tracked, resource: Document, fieldname: str, old, new) -> dict:
	label = spec.fields[fieldname]
	field = resource.meta.get_field(fieldname)
	if field.fieldtype in SUMMARY_FIELDTYPES:
		return get_detail(label)
	if field.fieldtype == "Check":
		inverted = fieldname in spec.inverted
		return get_detail(label, get_switch(old, inverted), get_switch(new, inverted))
	if field.fieldtype == "Link":
		return get_detail(label, get_link_title(field.options, old), get_link_title(field.options, new))

	return get_detail(label, old, new)


def get_switch(value, inverted: bool) -> str:
	return "on" if bool(cint(value)) != inverted else "off"


def get_table_detail(spec: Tracked, resource: Document, table: str, diff: dict) -> dict:
	"""Removed rows on the left, added rows on the right. A changed row shows on both sides."""
	before, after = get_row_sides(resource, table, diff)
	old, new = get_row_labels(spec, resource, table, before), get_row_labels(spec, resource, table, after)
	return get_detail(spec.fields[table], old, new)


def get_row_sides(resource: Document, table: str, diff: dict) -> tuple[list[dict], list[dict]]:
	"""The rows of one table before and after a save."""
	rows = {row.name: row.as_dict() for row in resource.get(table)}
	before = [row for name, row in diff.get("removed") or [] if name == table]
	after = [row for name, row in diff.get("added") or [] if name == table]
	for name, _index, row_name, changed in diff.get("row_changed") or []:
		if name == table:
			# An older Version can name a row the document no longer has.
			row = rows.get(row_name, {})
			after.append({**row, **{field: new for field, _old, new in changed}})
			before.append({**row, **{field: old for field, old, _new in changed}})

	return before, after


def get_row_labels(spec: Tracked, resource: Document, table: str, rows: list[dict]) -> str | None:
	child_meta = frappe.get_meta(resource.meta.get_field(table).options)
	return ", ".join(get_row_label(child_meta, row, spec.row_fields[table]) for row in rows) or None


def get_row_label(meta, row: dict, fields: tuple[str, ...]) -> str:
	values = []
	for fieldname in fields:
		field = meta.get_field(fieldname)
		value = row.get(fieldname)
		values.append(get_link_title(field.options, value) if field.fieldtype == "Link" else value)

	return " · ".join(str(value) for value in values if value)


def get_link_title(doctype: str, name: str | None) -> str | None:
	"""The name people know a linked record by. A deleted record keeps its ID."""
	title_field = frappe.get_meta(doctype).title_field
	if not name or not title_field:
		return name

	return frappe.db.get_value(doctype, name, title_field, cache=True) or name


def get_action_details(action: Document) -> list[dict]:
	# Only a finished resize confirms the new plan.
	if action.action != "resize" or action.status != "Succeeded":
		return []

	configuration = action.get_resize_configuration()
	if not configuration.plan or configuration.plan == configuration.from_plan:
		return []

	return [
		get_detail(
			"Plan",
			get_link_title("Plan", configuration.from_plan),
			get_link_title("Plan", configuration.plan),
		)
	]


def get_detail(label: str, old=None, new=None) -> dict[str, Any]:
	"""One change as the console shows it. The API translates the label for the reader."""
	return {"label": label, "from": truncate(old), "to": truncate(new)}


def truncate(value) -> str | None:
	if value in (None, ""):
		return None

	text = str(value)
	return text if len(text) <= MAX_VALUE_LENGTH else f"{text[: MAX_VALUE_LENGTH - 1]}…"


def on_doctype_update() -> None:
	"""Index the feed's paging order for a team and for one server."""
	frappe.db.add_index("Activity Event", ["team", "creation", "name"])
	frappe.db.add_index("Activity Event", ["server", "creation", "name"])
