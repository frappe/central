"""A stdio MCP server for Central's API, driven by the OpenAPI document.

Environment:
	CENTRAL_URL            site URL, for example https://central.example.com
	CENTRAL_API_KEY        API key of the user the server acts as
	CENTRAL_API_SECRET     that user's API secret

Run: uv run --with-requirements mcp_server/requirements.txt mcp_server/server.py
"""

from __future__ import annotations

import os

import httpx
from mcp.server.mcpserver import MCPServer

from mcp_server.operations import (
	build_request,
	first_record,
	input_schema,
	keep_fields,
	normalise,
	operation_index,
	search,
	validate,
)

CENTRAL_URL = os.environ.get("CENTRAL_URL", "").rstrip("/")
API_KEY = os.environ.get("CENTRAL_API_KEY", "")
API_SECRET = os.environ.get("CENTRAL_API_SECRET", "")
SPEC_METHOD = "/api/method/central.api.openapi.document"
GUIDE_PATH = "/assets/central/agents.md"
TIMEOUT = 30.0

if not (CENTRAL_URL and API_KEY and API_SECRET):
	raise SystemExit("Set CENTRAL_URL, CENTRAL_API_KEY and CENTRAL_API_SECRET.")

CLIENT = httpx.Client(
	base_url=CENTRAL_URL,
	headers={"Authorization": f"token {API_KEY}:{API_SECRET}"},
	timeout=TIMEOUT,
)
INDEX = operation_index(CLIENT.get(SPEC_METHOD).raise_for_status().json()["message"])
SERVER = MCPServer(
	"central",
	instructions=(
		"Find an operation with search_operations, read its arguments with get_operation, then run it "
		"with call_operation.\n\n" + CLIENT.get(GUIDE_PATH).raise_for_status().text
	),
)


def search_operations(query: str, limit: int = 10) -> dict:
	"""Find Central API operations by words in their id, summary, description or tag."""
	results = search(INDEX, query, limit)
	answer = {"query": query, "count": len(results), "results": results}
	if not results:
		answer["note"] = "No operation holds all of those words. Try one word, for example ticket."

	return answer


def get_operation(operation: str) -> dict:
	"""The arguments and behaviour of one operation."""
	entry = INDEX.get(operation)
	if entry is None:
		return {"error": f"Unknown operation: {operation}"}

	return {
		"operation": operation,
		"summary": entry.get("summary", ""),
		"description": entry.get("description", ""),
		"changes_data": not entry["x-mcp"]["read_only"],
		"arguments": input_schema(entry),
		"endpoint": f"{CENTRAL_URL}{entry['path']}",
	}


def call_operation(operation: str, arguments: dict, fields: list[str] | None = None) -> dict:
	"""Run one operation as the token's user and return its answer.
	For a large answer, pass top-level record keys in `fields`, for example ["name", "status"]."""
	entry = INDEX.get(operation)
	if entry is None:
		return {"error": f"Unknown operation: {operation}"}

	problem = validate(entry, arguments)
	if problem:
		return {"error": problem}

	method, path, request = build_request(entry, arguments)
	response = CLIENT.request(method, path, **request)
	if response.status_code >= 400:
		return {"error": response.text[:1000], "status": response.status_code}

	message = response.json().get("message", response.json())
	if fields:
		trimmed = keep_fields(message, fields)
		if first_record(message) and not first_record(trimmed):
			keys = sorted(first_record(message))
			return {"error": f"No record has any of {fields}. Name keys inside each record, such as {keys}."}
		message = trimmed

	return normalise(message)


SERVER.add_tool(search_operations, name="search_operations", description="Find Central API operations.")
SERVER.add_tool(get_operation, name="get_operation", description="Read one operation's arguments.")
SERVER.add_tool(
	call_operation,
	name="call_operation",
	description=(
		"Run one operation as the token's user. Pass the arguments `required` lists. For a large "
		'answer, pass top-level record keys in `fields`, for example ["name", "status"].'
	),
	annotations={"destructiveHint": True},
)

if __name__ == "__main__":
	SERVER.run()
