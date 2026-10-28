from __future__ import annotations

import re
from typing import Annotated, Literal

import frappe
import requests
from frappe import _
from frappe.flow import ToolContext, tool

from central.integrations.atlas import AtlasClient
from central.integrations.pilot import read_pilot, write_pilot
from central.investigator.access import refuse_destruction, require_operator, require_read_write
from central.investigator.scrub import scrub, scrub_value

NAME = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
PILOT_PATH = re.compile(rf"{NAME}(/{NAME})*")
# Pilot reads that return a credential, a login, or a raw backup file.
PILOT_DENIED_READ_PATHS = re.compile(
	r"(auth|bootstrap|editor|git|settings|setup)(/.*)?"
	r"|sites/[^/]+/(configuration|central|login|account-url|integrations|uploads)(/.*)?"
	r"|sites/[^/]+/backups/[^/]+/(download-links|files)(/.*)?"
)
# Pilot changes to code, credentials, or setup, or that run SQL.
PILOT_DENIED_WRITE_PATHS = re.compile(
	r"(auth|editor|git|setup|ssh-keys|database/queries)(/.*)?"
	r"|sites/[^/]+/(central|login|uploads|integrations)(/.*)?"
)
# Performance data must keep exact numbers and query text, so it is not scrubbed.
UNSCRUBBED_READ_PATHS = re.compile(
	r"(database|monitor)(/.*)?|metrics|system|storage|waf|sites/[^/]+/(monitoring|uptime|storage)"
)
MAXIMUM_TEXT_CHARACTERS = 20000

READ_QUERY = re.compile(r"\s*(select|with|explain|show|describe|desc)\b", re.IGNORECASE)
# A second statement, a file write, or the password table.
REFUSED_QUERY = re.compile(r";\s*\S|\binto\s+(outfile|dumpfile)\b|__auth", re.IGNORECASE)
QUERY_TIMEOUT_SECONDS = 10

Window = Literal["30m", "1h", "6h", "12h", "24h", "1w"]


@tool
def send_pilot_read_request(
	server: Annotated[str, "Virtual Machine name."],
	path: Annotated[str, "Admin API path after /api/v1/, such as tasks or sites/<site>/monitoring."],
	params: Annotated[
		dict | None,
		'Query parameters, such as {"status": "failed"} or {"lines": 500, "search": "Traceback"}.',
	] = None,
	*,
	ctx: ToolContext,
) -> dict | list | str:
	"""Read any GET path of the Pilot Admin API of one server. Pilot runs the benches and sites inside the VM.

	Search the Pilot knowledge base for docs/admin-api-reference.md to find a path and its parameters.
	Paths that return a credential, a login, or a backup file are refused. Performance data (database,
	monitor, metrics, system, storage, site monitoring) comes back exact. Other results are scrubbed.
	Text output keeps its last 20000 characters.
	"""
	require_operator(ctx)
	path = normalize_pilot_path(path)
	if not PILOT_PATH.fullmatch(path) or PILOT_DENIED_READ_PATHS.fullmatch(path):
		frappe.throw(_("The agent cannot read the Pilot path {0}.").format(path), frappe.PermissionError)

	result = read_pilot(server, f"/api/v1/{path}", params)
	if UNSCRUBBED_READ_PATHS.fullmatch(path):
		return result[-MAXIMUM_TEXT_CHARACTERS:] if isinstance(result, str) else result
	if isinstance(result, str):
		return scrub(result)[-MAXIMUM_TEXT_CHARACTERS:]
	return scrub_value(result)


@tool
def get_performance_snapshot(
	server: Annotated[str, "Virtual Machine name."],
	site: Annotated[str | None, "Site name. Without it, only the server and database are read."] = None,
	window: Window = "1h",
	*,
	ctx: ToolContext,
) -> dict:
	"""Read the first pass of a performance investigation in one call. Nothing is scrubbed.

	Returns, keyed by Pilot path: system, monitor/status (with each service process), monitor/history,
	database/diagnostics, processlist, and lockwaits. With a site, also its monitoring (slowest requests,
	jobs, reports, and queries) and the database performance report for time consuming and full table
	scan queries. A path that fails has {"error": ...} and does not stop the others.
	"""
	require_operator(ctx)
	if site and not re.fullmatch(NAME, site):
		frappe.throw(_("{0} is not a site name.").format(site))

	snapshot = {}
	for label, path, params in _snapshot_reads(site, window):
		try:
			snapshot[label] = read_pilot(server, f"/api/v1/{path}", params)
		except Exception as error:
			snapshot[label] = {"error": str(error)}
	return snapshot


def _snapshot_reads(site: str | None, window: str) -> list[tuple[str, str, dict | None]]:
	reads = [
		("system", "system", None),
		("monitor/status", "monitor/status", None),
		("monitor/history", "monitor/history", {"window": window}),
		("database/diagnostics", "database/diagnostics", None),
		("database/processlist", "database/processlist", None),
		("database/lockwaits", "database/lockwaits", None),
	]
	if site:
		reads.append((f"sites/{site}/monitoring", f"sites/{site}/monitoring", {"window": window}))
		for report_type in ("time_consuming_queries", "full_table_scan_queries"):
			params = {"report_type": report_type, "site": site, "limit": 10}
			reads.append(
				(f"database/performance-report/{report_type}", "database/performance-report", params)
			)
	return reads


@tool
def run_database_query(
	server: Annotated[str, "Virtual Machine name."],
	site: Annotated[str, "Site whose database the query reads."],
	query: Annotated[str, "One SELECT, WITH, EXPLAIN, SHOW, or DESCRIBE statement."],
	*,
	ctx: ToolContext,
) -> dict:
	"""Run one read-only query on a site database, such as EXPLAIN of a slow query or SHOW INDEX FROM a table.

	The query runs in a read-only transaction and stops after 10 seconds. Prefer EXPLAIN to running a slow
	query. The result is exact and is not scrubbed. The password table is refused.
	"""
	require_operator(ctx)
	query = query.strip().removesuffix(";")
	if not READ_QUERY.match(query) or REFUSED_QUERY.search(query):
		frappe.throw(_("The agent can run only one read-only query."), frappe.PermissionError)

	if re.match(r"\s*(select|with)\b", query, re.IGNORECASE):
		query = f"SET STATEMENT max_statement_time={QUERY_TIMEOUT_SECONDS} FOR {query}"
	payload = {"site": site, "query": query, "read_only": True}
	return write_pilot(server, "POST", "/api/v1/database/queries", payload)


def _confirm_pilot_write(arguments: dict) -> str:
	return _("Send {0} /api/v1/{1} to the Pilot of {2} with {3}?").format(
		arguments.get("method"),
		arguments.get("path"),
		arguments.get("server"),
		arguments.get("payload") or {},
	)


@tool(requires_confirmation=True, confirm_prompt=_confirm_pilot_write)
def send_pilot_write_request(
	server: Annotated[str, "Virtual Machine name."],
	method: Literal["POST", "PUT", "PATCH"],
	path: Annotated[str, "Admin API path after /api/v1/, such as sites/<site>/actions/clear-cache."],
	payload: Annotated[dict | None, 'JSON body, such as {"process_id": 42}.'] = None,
	*,
	ctx: ToolContext,
) -> dict | list | str:
	"""Change something through the Pilot Admin API of one server. Needs a read-write session.

	Examples: POST sites/<site>/actions/clear-cache, sites/<site>/actions/migrate, benches/<bench>/actions/restart,
	tasks/<task>/actions/retry, task-worker/actions/start, migrations/<id>/actions/retry, database/processlist/kill.
	Code, credentials, setup, SQL, and any destruction are refused. Every result is scrubbed.
	"""
	require_read_write(ctx)
	path = normalize_pilot_path(path)
	if not PILOT_PATH.fullmatch(path) or PILOT_DENIED_WRITE_PATHS.fullmatch(path):
		frappe.throw(_("The agent cannot change the Pilot path {0}.").format(path), frappe.PermissionError)
	refuse_destruction(path)

	return scrub_value(write_pilot(server, method, f"/api/v1/{path}", payload))


@tool
def start_region_investigation(
	region: Annotated[str, "Region name, such as pl-waw-1."],
	problem: Annotated[str, "The problem to investigate, with the symptom and when it started."],
	context: Annotated[
		dict | None, "Facts that help, such as the Atlas VM ID, the Atlas host ID, alert names, and times."
	] = None,
	*,
	ctx: ToolContext,
) -> dict:
	"""Hand a host-side problem to the read-only investigator of one region.

	The investigator reads that region's telemetry, records, and Metal hosts, and changes nothing.
	It takes a few minutes. Poll get_region_investigation until the status is completed or failed.
	"""
	client = AtlasClient.for_operator(frappe.get_doc("Region", region))
	investigation = client.create_investigation(problem, context, ctx.user)
	return {"region": region, "id": investigation["id"], "status": investigation["status"]}


@tool
def get_region_investigation(
	region: Annotated[str, "Region name."],
	investigation_id: Annotated[str, "ID from start_region_investigation."],
	*,
	ctx: ToolContext,
) -> dict:
	"""Read one regional investigation: its status, its report, and the log of its tool calls.

	When the status is completed or failed, use its report as evidence and name the investigation ID.
	"""
	return AtlasClient.for_operator(frappe.get_doc("Region", region)).get_investigation(investigation_id)


def normalize_pilot_path(path: str) -> str:
	return path.strip().removeprefix("/").removeprefix("api/v1/").strip("/")


def _confirm_infra_alert(arguments: dict) -> str:
	return _("Post this message to the infra alerts Raven channel?\n\n{0}").format(
		arguments.get("markdown_message")
	)


@tool(requires_confirmation=True, confirm_prompt=_confirm_infra_alert)
def send_infra_alert_to_raven(
	markdown_message: Annotated[str, "The alert in Markdown."],
	*,
	ctx: ToolContext,
) -> dict:
	"""Post an infrastructure alert to the Raven channel that Central Settings names."""
	require_operator(ctx)
	url = frappe.get_cached_doc("Central Settings").get_password(
		"infra_alert_webhook_url", raise_exception=False
	)
	if not url:
		frappe.throw(_("Set the Infra Alert Webhook URL in Central Settings."))

	response = requests.post(
		url, json={"message": markdown_message[:MAXIMUM_TEXT_CHARACTERS]}, timeout=(5, 10)
	)
	response.raise_for_status()
	return {"status": "sent"}
