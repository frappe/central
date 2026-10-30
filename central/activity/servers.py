from typing import Any

import frappe
from frappe.utils import cint, flt

from central.activity.changes import get_detail, truncate, version_context
from central.central.doctype.activity_event.activity_event import ActivityEvent

TERMINAL_ACTION_STATES = ("Succeeded", "Failed", "Timed Out")
ACTION_EVENTS = {
	"start": "server.started",
	"stop": "server.stopped",
	"restart": "server.restarted",
	"resize": "server.resized",
	"terminate": "server.terminated",
}
SNAPSHOT_EVENTS = {
	"Available": "snapshot.taken",
	"Deleted": "snapshot.deleted",
	"Failed": "snapshot.failed",
}
VERSION_FIELDS = {
	"disk_gigabytes": "Disk",
	"memory_megabytes": "Memory",
	"plan": "Plan",
	"public_ipv4": "Public IPv4",
	"public_ipv6": "Public IPv6",
	"ssh_keys": "SSH keys",
	"title": "Server name",
	"vcpus": "vCPUs",
	"firewall_rules": "Firewall rules",
	"has_ipv4_internet": "IPv4 internet access",
	"is_firewall_enabled": "Firewall",
	"is_termination_protected": "Termination protection",
	"skip_automatic_snapshot": "Automatic snapshots",
}
# Diffs too wide for two short values, so the row renders as one label.
SUMMARY_FIELDS = {"firewall_rules", "ssh_keys"}
CHECK_FIELDS = {
	"has_ipv4_internet",
	"is_firewall_enabled",
	"is_termination_protected",
	"skip_automatic_snapshot",
}


def record_server_created(server) -> str | None:
	return ActivityEvent.record(
		"server.created",
		resource_type="Virtual Machine",
		resource_name=server.name,
		key=f"server:{server.name}:created",
		actor=server.owner,
		occurred_at=server.creation,
	)


def record_action_terminal(action) -> str | None:
	# create already has its Server created event, and the other states are still pending
	event = ACTION_EVENTS.get(action.action)
	if not action.server or not event or action.status not in TERMINAL_ACTION_STATES:
		return None

	return ActivityEvent.record(
		event,
		resource_type="Virtual Machine",
		resource_name=action.server,
		key=f"action:{action.name}",
		actor=action.requested_by,
		occurred_at=action.completed_at or action.creation,
		status=action.status,
		details=get_action_details(action),
		error=action.error_message,
		reference=("Resource Action", action.name),
	)


def record_snapshot_terminal(snapshot) -> str | None:
	event = SNAPSHOT_EVENTS.get(snapshot.status)
	if not event:
		return None

	# billing updates bump modified later, so an available snapshot keeps its creation time;
	# a deleted or failed snapshot is stamped when its status last changed
	occurred_at = snapshot.creation if snapshot.status == "Available" else snapshot.modified
	return ActivityEvent.record(
		event,
		resource_type="Virtual Machine",
		resource_name=snapshot.server,
		key=f"snapshot:{snapshot.name}:{snapshot.status}",
		actor=snapshot.requested_by or snapshot.owner,
		occurred_at=occurred_at,
		status=snapshot.status,
		details=get_snapshot_details(snapshot),
		error=snapshot.error_detail,
		reference=("VM Snapshot", snapshot.name),
	)


def record_snapshot_kept(snapshot) -> str | None:
	return ActivityEvent.record(
		"snapshot.kept",
		resource_type="Virtual Machine",
		resource_name=snapshot.server,
		key=f"snapshot:{snapshot.name}:kept",
		details=get_snapshot_details(snapshot),
		reference=("VM Snapshot", snapshot.name),
	)


def record_server_version(version, changes) -> str | None:
	tables = _changed_tables(changes)
	details = _version_details(changes, tables)
	if not details:
		return None

	event = "server.renamed" if _is_rename(changes, tables) else "server.configured"
	return ActivityEvent.record(
		event,
		resource_type="Virtual Machine",
		resource_name=version.docname,
		key=f"version:{version.name}",
		details=details,
		**version_context(version),
	)


def _changed_tables(changes) -> set[str]:
	return {row[0] for row in [*changes.added, *changes.removed, *changes.row_changed]}


def _version_details(changes, tables: set[str]) -> list[dict[str, Any]]:
	details = [
		get_setting_detail(fieldname, old, new)
		for fieldname, (old, new) in changes.changed.items()
		if fieldname in VERSION_FIELDS
	]
	details += [get_setting_detail(table) for table in sorted(tables) if table in VERSION_FIELDS]

	# One row per label; a field and its child table can describe the same setting.
	return list({detail["label"]: detail for detail in details}.values())


def _is_rename(changes, tables: set[str]) -> bool:
	changed_fields = {fieldname for fieldname in changes.changed if fieldname in VERSION_FIELDS}
	return changed_fields == {"title"} and not tables


def record_setting(server, fieldname: str, old, new) -> str | None:
	"""A setting that arrives through db_set has no Version row to read."""
	if old == new:
		return None

	return ActivityEvent.record(
		"server.configured",
		resource_type="Virtual Machine",
		resource_name=server.name,
		key=f"setting:{server.name}:{fieldname}:{frappe.utils.now_datetime()}",
		details=[get_setting_detail(fieldname, old, new)],
	)


def get_setting_detail(fieldname: str, old=None, new=None) -> dict[str, Any]:
	label = VERSION_FIELDS.get(fieldname)
	if not label:
		raise ValueError(f"Activity event cannot describe setting {fieldname}")

	if fieldname in SUMMARY_FIELDS:
		return get_detail(label)
	if fieldname in CHECK_FIELDS:
		return get_detail(label, _check_value(fieldname, old), _check_value(fieldname, new))
	return get_detail(label, old, new)


def _check_value(fieldname: str, value) -> str:
	# skip_automatic_snapshot is stored inverted to its label
	return "on" if bool(cint(value)) != (fieldname == "skip_automatic_snapshot") else "off"


def get_action_details(action) -> list[dict[str, Any]]:
	# only a succeeded resize confirms its shape; a failed one would otherwise claim it
	if action.action != "resize" or action.status != "Succeeded":
		return []
	payload = frappe.parse_json(action.request_payload or "{}")
	if not isinstance(payload, dict):
		return []

	return _resize_details(payload)


def _resize_details(payload: dict) -> list[dict[str, Any]]:
	shape = payload.get("shape") or {}
	origin = payload.get("from_shape") or {}
	details = _plan_details(payload)
	details += [
		get_detail(label, _quantity(origin.get(field)), _quantity(shape.get(field)))
		for field, label in (
			("vcpus", "vCPUs"),
			("memory_megabytes", "Memory"),
			("disk_gigabytes", "Disk"),
		)
		if origin.get(field) != shape.get(field) and shape.get(field) not in (None, "")
	]
	return details


def _plan_details(payload: dict) -> list[dict[str, Any]]:
	if not payload.get("plan") or payload["plan"] == payload.get("from_plan"):
		return []

	return [get_detail("Plan", payload.get("from_plan"), payload["plan"])]


def _quantity(value) -> str | None:
	if value in (None, ""):
		return None
	number = flt(value)
	return str(int(number)) if number == int(number) else truncate(value)


def get_snapshot_details(snapshot) -> list[dict[str, Any]]:
	details = [get_detail("Snapshot", None, snapshot.title or snapshot.name)]
	if snapshot.size_mib:
		details.append(get_detail("Size", None, f"{snapshot.size_mib} MiB"))
	return details
