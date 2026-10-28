from __future__ import annotations

import re
from typing import Annotated

import frappe
from frappe import _
from frappe.flow import ToolContext, tool

from central.iam import user_has_operator_bypass
from central.integrations.atlas import AtlasClient
from central.integrations.pilot import read_pilot
from central.investigator.scrub import scrub, scrub_value

NAME = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
# Pilot Admin API paths, after /api/v1/, that the investigator can read. Site configuration, backup
# download links, the file editor, and the Central proxy return secrets or files, so they are not here.
PILOT_READ_PATHS = [
	re.compile(pattern.replace("{name}", NAME))
	for pattern in (
		"health",
		"benches",
		"benches/{name}",
		"apps",
		"apps/{name}",
		"sites",
		"sites/{name}",
		"sites/{name}/(apps|monitoring|uptime|storage|backups|domains)",
		"sites/{name}/tasks/{name}",
		"tasks",
		"tasks/{name}",
		"tasks/{name}/output/content",
		"task-worker",
		"logs",
		"logs/{name}",
		"database/(diagnostics|processlist|lockwaits|size|table-sizes|performance-report)",
		"database/history",
		"monitor/(status|history)",
		"system",
		"metrics",
		"storage",
		"migrations",
		"migrations/(current|{name})",
		"notifications",
		"audit-events",
	)
]
MAXIMUM_TEXT_CHARACTERS = 20000


@tool
def read_pilot_api(
	server: Annotated[str, "Virtual Machine name."],
	path: Annotated[str, "Admin API path after /api/v1/, such as tasks or sites/<site>/monitoring."],
	params: Annotated[
		dict | None,
		'Query parameters, such as {"status": "failed"} or {"lines": 500, "search": "Traceback"}.',
	] = None,
	*,
	ctx: ToolContext,
) -> dict | list | str:
	"""Read the Pilot Admin API of one server. Pilot runs the benches and sites inside the VM.

	Paths: health; benches, benches/<bench>; apps, apps/<app>; sites, sites/<site>, and
	sites/<site>/apps, monitoring, uptime, storage, backups, domains, tasks/<task>; tasks (params
	status, limit), tasks/<task>, tasks/<task>/output/content, task-worker; logs, logs/<file> (params
	lines, search); database/diagnostics, processlist, lockwaits, size, table-sizes, performance-report,
	history; monitor/status, monitor/history (param window, such as 1h); system; metrics; storage;
	migrations, migrations/current, migrations/<id>; notifications; audit-events.
	Every result is scrubbed. Text output keeps its last 20000 characters.
	"""
	_require_operator(ctx)
	path = path.strip().removeprefix("/").removeprefix("api/v1/").strip("/")
	if not any(pattern.fullmatch(path) for pattern in PILOT_READ_PATHS):
		frappe.throw(
			_("The investigator cannot read the Pilot path {0}.").format(path), frappe.PermissionError
		)

	result = read_pilot(server, f"/api/v1/{path}", params)
	if isinstance(result, str):
		return scrub(result)[-MAXIMUM_TEXT_CHARACTERS:]
	return scrub_value(result)


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


def _require_operator(ctx: ToolContext) -> None:
	if not user_has_operator_bypass(ctx.user):
		frappe.throw(_("Only an operator can read a server's Pilot."), frappe.PermissionError)
