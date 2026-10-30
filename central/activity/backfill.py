from collections import defaultdict

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

from central.activity.changes import get_changes
from central.activity.servers import (
	record_action_terminal,
	record_server_created,
	record_server_version,
	record_snapshot_terminal,
)

BATCH_SIZE = 500


def backfill_server_events(days: int = 30) -> int:
	"""Rebuild the feed for the records Central still keeps, within the retention window.
	Runs for existing sites on migrate and for demo seeds."""
	cutoff = add_days(now_datetime(), -days)
	servers = frappe.get_all("Virtual Machine", fields=["name", "creation", "owner"])
	if not servers:
		return 0

	names = [row.name for row in servers]
	actions = _group(_all_actions(names), "server")
	snapshots = _group(_all_snapshots(names), "server")
	versions = _group(_all_versions(names), "docname")

	made = 0
	for server in servers:
		if _is_after(server.creation, cutoff):
			made += _record(record_server_created, server)
		made += _record_each(
			record_action_terminal,
			actions.get(server.name, []),
			cutoff,
			lambda action: action.completed_at or action.creation,
		)
		made += _record_each(
			record_snapshot_terminal,
			snapshots.get(server.name, []),
			cutoff,
			lambda snapshot: snapshot.creation if snapshot.status == "Available" else snapshot.modified,
		)
		made += _record_each(
			record_server_version,
			versions.get(server.name, []),
			cutoff,
			lambda version: version.creation,
			lambda version: (version, get_changes(version.data)),
		)

	return made


def _record(record, *args) -> int:
	try:
		return int(bool(record(*args)))
	except Exception:
		# A stale user link or corrupt payload on one old row must not abort migrate.
		frappe.log_error(title="Activity backfill skipped a row", message=frappe.get_traceback())
		return 0


def _record_each(record, sources: list, cutoff, time_of, prepare=None) -> int:
	prepare = prepare or (lambda source: (source,))
	return sum(_record(record, *prepare(source)) for source in sources if _is_after(time_of(source), cutoff))


def _is_after(value, cutoff) -> bool:
	return bool(value and get_datetime(value) >= cutoff)


def _group(rows: list, field: str) -> dict[str, list]:
	grouped = defaultdict(list)
	for row in rows:
		grouped[row[field]].append(row)

	return grouped


def _all_actions(servers: list[str]) -> list:
	return _rows_for(
		"Resource Action",
		"server",
		servers,
		[
			"name",
			"server",
			"action",
			"status",
			"requested_by",
			"creation",
			"completed_at",
			"error_message",
			"request_payload",
		],
	)


def _all_snapshots(servers: list[str]) -> list:
	return _rows_for(
		"VM Snapshot",
		"server",
		servers,
		[
			"name",
			"server",
			"status",
			"requested_by",
			"owner",
			"creation",
			"modified",
			"title",
			"size_mib",
			"error_detail",
		],
	)


def _all_versions(servers: list[str]) -> list:
	rows = []
	for batch in _batches(servers):
		rows.extend(
			frappe.get_all(
				"Version",
				filters={"ref_doctype": "Virtual Machine", "docname": ("in", batch)},
				fields=["name", "ref_doctype", "docname", "owner", "creation", "data"],
				order_by="creation asc",
			)
		)

	return rows


def _rows_for(doctype: str, field: str, servers: list[str], fields: list[str]) -> list:
	rows = []
	for batch in _batches(servers):
		rows.extend(
			frappe.get_all(
				doctype,
				filters={field: ("in", batch)},
				fields=fields,
				order_by="creation asc",
			)
		)

	return rows


def _batches(values: list[str]):
	for start in range(0, len(values), BATCH_SIZE):
		yield values[start : start + BATCH_SIZE]
