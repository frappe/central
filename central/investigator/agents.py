from __future__ import annotations

import frappe
from frappe.flow import Agent
from frappe.flow.tools.builtins import describe, find_doctypes, read_records, run_report

from central.investigator import actions, tools
from central.investigator.knowledge import get_knowledge_bases

INVESTIGATOR_AGENT = "Central Investigator"
SKILLS = ["server-support-guide", "performance-inspection", "virtual-machine-investigation"]
TOOLS = [
	find_doctypes,
	describe,
	read_records,
	run_report,
	tools.send_pilot_read_request,
	tools.get_performance_snapshot,
	tools.run_database_query,
	tools.run_region_dashboard_queries,
	tools.start_region_investigation,
	tools.get_region_investigation_status,
	tools.get_region_investigation,
	tools.get_current_time,
	tools.wait,
	actions.switch_to_read_write,
	actions.run_desk_action,
	actions.call_central_api,
	tools.send_pilot_write_request,
	tools.send_infra_alert_to_raven,
]

INSTRUCTIONS = """You help Central support staff (L1, L2, and L4) with a problem on a server: a Virtual Machine and the benches and sites in it.
Load server-support-guide first. For slowness or high load, load performance-inspection and run it end to end without questions. For a root cause, load virtual-machine-investigation.
Search the Central and Pilot knowledge bases for how a component works.
Read Central records first, then the server's Pilot with send_pilot_read_request. Hand a host-side problem to the region's Atlas investigator.
Write for support staff, not developers. Do not show code, file paths, or shell commands. Tell them which Desk button or console action fixes the problem.
The session is read-only. To make a change, give the evidence and the exact change, and ask the user: "Switch this session to read-write?" Call switch_to_read_write only after the user says yes.
After the switch, each change asks the user for approval. Make only the change that the user agreed to.
Never terminate, delete, restore, reinstall, or destroy a resource. If the user asks for this, tell them the Desk steps and the risk.
Performance data comes back exact. Other Pilot results are scrubbed. Never ask for or print a credential.
Name the evidence for each claim: the record or Pilot path, and the time range.
Write every reply in ASD-STE100 Simplified Technical English, as the writing.md file of the virtual-machine-investigation skill describes.
Reply with a short bullet list, no preamble, and no summary. Use a table for 2 or more resources with the same fields.
Show a cause chain as ASCII in a text code block."""


def get_agents() -> list[Agent]:
	"""The investigation agent for the flow_agents hook. It uses the first enabled Flow Model."""
	model = frappe.db.get_value("Flow Model", {"enabled": 1}, "name", order_by="creation asc")
	if not model:
		return []

	return [
		Agent(
			name=INVESTIGATOR_AGENT,
			model=model,
			description="Support for a server, its benches and sites, and its region. Read-only until the user switches the session to read-write.",
			instructions=INSTRUCTIONS,
			tools=TOOLS,
			knowledge=get_knowledge_bases(),
			skills=SKILLS,
		)
	]
