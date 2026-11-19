from collections.abc import Iterator
from itertools import batched

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime

from central.central.doctype.activity_event.activity_event import (
	FEED_CACHE,
	get_action_event,
	get_lifecycle_event,
	get_retention_days,
	get_version_events,
	has_tracked_change,
)
from central.central.doctype.activity_event.tracked import ACTION_EVENTS, TRACKED
from central.infrastructure.doctype.resource_action.resource_action import TERMINAL_STATES

BATCH_SIZE = 1000
COLUMNS = (
	"name",
	"owner",
	"modified_by",
	"modified",
	"creation",
	"team",
	"server",
	"resource_type",
	"resource_name",
	"resource_label",
	"event",
	"category",
	"required_capability",
	"actor",
	"status",
	"details",
	"error",
	"reference_doctype",
	"reference_name",
)


def backfill(days: int | None = None) -> int:
	"""Replay the history the site already keeps into the feed: Versions, creations, deletions
	and finished server actions. Only sources older than the first recorded event are read,
	so a live event is never written twice. Returns the number of events written."""
	first = frappe.db.get_value("Activity Event", {}, "creation", order_by="creation asc")
	window = (add_days(now_datetime(), -(days or get_retention_days())), first or now_datetime())
	events = (
		event
		for source in (
			get_version_events_in,
			get_created_events_in,
			get_deleted_events_in,
			get_action_events_in,
		)
		for event in source(window)
		if event
	)

	written = 0
	for chunk in batched(events, BATCH_SIZE, strict=False):
		frappe.db.bulk_insert("Activity Event", COLUMNS, [get_values(event) for event in chunk])
		written += len(chunk)

	frappe.cache.delete_keys(f"{FEED_CACHE}|")
	return written


def get_version_events_in(window: tuple) -> Iterator[dict | None]:
	"""Each tracked Version, with its document read once however many Versions it has."""
	for doctype, spec in TRACKED.items():
		versions = frappe.get_all(
			"Version",
			filters=[*in_window("creation", window), ["ref_doctype", "=", doctype]],
			fields=["name", "ref_doctype", "docname", "owner", "creation", "data"],
		)
		changes = [(version, frappe.parse_json(version.data)) for version in versions]
		changes = [(version, diff) for version, diff in changes if has_tracked_change(spec, diff)]
		documents = get_documents(doctype, {version.docname for version, _diff in changes})
		for version, diff in changes:
			# A deleted document's Versions are removed after its delete commits.
			if document := documents.get(version.docname):
				yield from get_version_events(version, document, diff)


def get_documents(doctype: str, names: set[str]) -> dict[str, Document]:
	if not names:
		return {}

	existing = frappe.get_all(doctype, filters={"name": ("in", names)}, pluck="name")
	return {name: frappe.get_doc(doctype, name) for name in existing}


def get_created_events_in(window: tuple) -> Iterator[dict | None]:
	for doctype, spec in TRACKED.items():
		if spec.lifecycle:
			for row in frappe.get_all(doctype, filters=in_window("creation", window), fields=["*"]):
				yield get_lifecycle_event(
					frappe.get_doc({"doctype": doctype, **row}), "created", row.owner, row.creation
				)


def get_deleted_events_in(window: tuple) -> Iterator[dict | None]:
	"""Deleted Document keeps the whole record, its team included."""
	doctypes = [doctype for doctype, spec in TRACKED.items() if spec.lifecycle]
	rows = frappe.get_all(
		"Deleted Document",
		filters=[*in_window("creation", window), ["deleted_doctype", "in", doctypes]],
		fields=["data", "owner", "creation"],
	)
	for row in rows:
		yield get_lifecycle_event(
			frappe.get_doc(frappe.parse_json(row.data)), "deleted", row.owner, row.creation
		)


def get_action_events_in(window: tuple) -> Iterator[dict | None]:
	actions = frappe.get_all(
		"Resource Action",
		filters=[
			*in_window("completed_at", window),
			["action", "in", list(ACTION_EVENTS)],
			["status", "in", TERMINAL_STATES],
			["server", "is", "set"],
		],
		fields=["*"],
	)
	server_names = {action.server for action in actions}
	server_rows = frappe.get_all(
		"Virtual Machine", filters={"name": ("in", server_names or [""])}, fields=["name", "team", "title"]
	)
	servers = {row.name: frappe.get_doc({"doctype": "Virtual Machine", **row}) for row in server_rows}
	for row in actions:
		if row.server in servers:
			yield get_action_event(frappe.get_doc({"doctype": "Resource Action", **row}), servers[row.server])


def in_window(fieldname: str, window: tuple) -> list[list]:
	return [[fieldname, ">=", window[0]], [fieldname, "<", window[1]]]


def get_values(event: dict) -> tuple:
	"""A bulk insert skips the document lifecycle, so it sets the standard columns itself."""
	row = {
		**event,
		"name": frappe.generate_hash(length=10),
		"owner": "Administrator",
		"modified_by": "Administrator",
		"modified": event["creation"],
	}
	return tuple(row[column] for column in COLUMNS)
