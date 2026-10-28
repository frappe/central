from __future__ import annotations

import frappe
from frappe.flow import Agent
from frappe.flow.tools.builtins import describe, find_doctypes, read_records, run_report

from central.investigator import tools
from central.investigator.knowledge import get_knowledge_bases

INVESTIGATOR_AGENT = "Central Investigator"
SKILLS = ["virtual-machine-investigation"]
TOOLS = [
	find_doctypes,
	describe,
	read_records,
	run_report,
	tools.read_pilot_api,
	tools.start_region_investigation,
	tools.get_region_investigation,
]

INSTRUCTIONS = """You help a Central operator investigate a problem with a server: a Virtual Machine and the benches and sites in it.
Load the virtual-machine-investigation skill first and follow it. Search the Central and Pilot knowledge bases for how a component works.
Read Central records first, then the server's Pilot with read_pilot_api. Hand a host-side problem to the region's Atlas investigator.
You are read-only. If the fix needs a change, write the change as a recommendation for the operator.
Every Pilot result is scrubbed. Never ask for or print a credential.
Name the evidence for each claim: the tool, the record or Pilot path, and the time range.
Write every reply in ASD-STE100 Simplified Technical English, as the writing.md file of the skill describes.
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
			description="Read-only investigation of a server, its benches and sites, and its region.",
			instructions=INSTRUCTIONS,
			tools=TOOLS,
			knowledge=get_knowledge_bases(),
			skills=SKILLS,
		)
	]
