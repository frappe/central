from __future__ import annotations

import re
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe.utils import get_system_timezone, now_datetime
from frappe.utils.file_lock import LockTimeoutError
from frappe.utils.synchronization import filelock

from central.api.pilot import get_telemetry_base_url, region_id_of
from central.sso import mint_datum_token

CURSOR_KEY = "central:telemetry:error_log_cursor"
RESOURCE_ID = "central"
# Datum takes 1,000 lines a request. One request a minute stays under its rate limit.
MAXIMUM_LINES = 1_000
TRACEBACK_TAIL_CHARACTERS = 1_024
REQUEST_TIMEOUT_SECONDS = 30
EXCEPTION_LINE = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")
ERROR_LOG_FIELDS = ["name", "creation", "method", "error", "fingerprint", "trace_id", "metadata"]


class ErrorLogPublisher:
	"""Sends new Error Logs to the Datum of the Central telemetry region, so Beacon sees what fails in Central."""

	def __init__(self, region: str):
		self.region = region

	def publish(self) -> None:
		rows = self.get_new_error_logs()
		if rows and send_to_datum(
			self.region, "/v1/logs/ingest", {"lines": [to_log_line(row) for row in rows]}
		):
			frappe.cache.set_value(CURSOR_KEY, str(rows[-1].creation))

	def get_new_error_logs(self) -> list[frappe._dict]:
		"""Read after the cursor. The log store compares creation as text, so the cursor uses the same form.
		The first lower bound is stored before the first push, so a failed push does not move it forward."""
		cursor = frappe.cache.get_value(CURSOR_KEY)
		if not cursor:
			cursor = str(now_datetime() - timedelta(minutes=5))
			frappe.cache.set_value(CURSOR_KEY, cursor)
		return frappe.get_all(
			"Error Log",
			filters={"creation": [">", cursor]},
			fields=ERROR_LOG_FIELDS,
			order_by="creation asc",
			limit=MAXIMUM_LINES,
		)


def get_central_telemetry_region() -> str | None:
	"""The region whose Datum takes the Central telemetry: the one with Central Telemetry Region set."""
	return frappe.db.get_value("Region", {"is_central_telemetry_region": 1}, "name")


def send_to_datum(region: str, path: str, payload: dict) -> bool:
	"""Post one payload to the Datum of a region as Central. A failure is a warning, not an Error Log,
	so an unreachable Datum does not make a Central error each minute. Returns whether Datum took it."""
	url = get_telemetry_base_url(region)
	if not url:
		return False

	token = mint_datum_token(region_id_of(region), RESOURCE_ID)
	try:
		response = requests.post(
			f"{url.rstrip('/')}{path}",
			headers={"Authorization": f"Bearer {token}"},
			json=payload,
			timeout=REQUEST_TIMEOUT_SECONDS,
		)
		response.raise_for_status()
	except requests.RequestException as error:
		frappe.logger("central.telemetry").warning(f"Datum push to {path} failed: {error}")
		return False
	return True


def publish_error_logs() -> None:
	"""Scheduled every minute. Does nothing until a region has Central Telemetry Region set."""
	region = get_central_telemetry_region()
	if not region:
		return

	try:
		with filelock("central:telemetry:error-logs", timeout=0):
			ErrorLogPublisher(region).publish()
	except LockTimeoutError:
		return


def to_log_line(row: frappe._dict) -> dict:
	"""One Datum log line. The form data in the metadata stays out, because it can hold secrets."""
	metadata = frappe.parse_json(row.metadata or "{}") or {}
	traceback = (row.error or "").strip()
	last_line = traceback.splitlines()[-1] if traceback else ""
	match = EXCEPTION_LINE.match(last_line)
	title = (row.method or last_line).strip()
	created = row.creation.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(UTC)
	attributes = {
		"error_log": row.name,
		"fingerprint": row.fingerprint or "",
		"request_id": row.trace_id or "",
		"exception": match.group(1) if match else "",
		"unhandled": "1" if is_unhandled(title, last_line, metadata) else "0",
		"kind": metadata.get("type") or "",
		"path": metadata.get("path") or metadata.get("job_name") or "",
		"traceback": traceback[-TRACEBACK_TAIL_CHARACTERS:],
	}
	return {
		"ts": created.isoformat(),
		"product": "central",
		"service": "central",
		"level": "error",
		"source": "error_log",
		"message": title,
		"attributes": {name: value for name, value in attributes.items() if value},
	}


def is_unhandled(title: str, last_line: str, metadata: dict) -> bool:
	"""A job or request that raised, as opposed to an error that Central logs on purpose."""
	if metadata.get("type") == "background_job":
		return title == metadata.get("job_name")
	return metadata.get("type") == "http_request" and bool(last_line) and last_line.endswith(title)
