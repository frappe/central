from typing import Any

import frappe

MAX_LENGTH = 120


def record_version(version) -> None:
	"""Turn a tracked server change into activity. Team records change through their own
	controller, so one save cannot produce both a Version event and a lifecycle event."""
	if version.ref_doctype != "Virtual Machine":
		return

	from central.activity.servers import record_server_version

	record_server_version(version, get_changes(version.data))


def get_changes(data) -> frappe._dict:
	"""A Version payload as `changed` {field: (old, new)} plus its child-row lists.
	Old rows can carry malformed payloads, and a parse error must not abort a save or patch."""
	try:
		parsed = frappe.parse_json(data or "{}")
	except Exception:
		parsed = None
	if not isinstance(parsed, dict):
		parsed = {}

	return frappe._dict(
		changed=_changed_items(parsed.get("changed")),
		added=_rows(parsed.get("added")),
		removed=_rows(parsed.get("removed")),
		row_changed=_changed_rows(parsed.get("row_changed")),
	)


def _changed_items(items) -> dict[str, tuple[Any, Any]]:
	result: dict[str, tuple[Any, Any]] = {}
	for item in items or []:
		if isinstance(item, (list, tuple)) and len(item) >= 3:
			result[item[0]] = (item[1], item[2])
	return result


def _changed_rows(items) -> list[list | tuple]:
	return [row for row in items or [] if isinstance(row, (list, tuple)) and row]


def _rows(items) -> list[tuple[str, dict]]:
	return [
		(item[0], item[1])
		for item in items or []
		if isinstance(item, list | tuple) and len(item) >= 2 and isinstance(item[1], dict)
	]


def version_context(version) -> dict[str, Any]:
	"""The record arguments every Version-based event shares."""
	return {
		"actor": version.owner,
		"occurred_at": version.creation,
		"reference": ("Version", version.name),
	}


def get_detail(label: str, old=None, new=None) -> dict[str, Any]:
	# Store the English label; the API translates it for the reader's language.
	return {"label": label, "from": truncate(old), "to": truncate(new)}


def truncate(value) -> str | None:
	if value in (None, ""):
		return None
	text = str(value)
	return text if len(text) <= MAX_LENGTH else f"{text[: MAX_LENGTH - 1]}…"
