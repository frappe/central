"""Pure helpers behind the Central MCP server. No MCP SDK and no network here, so they are testable."""

from __future__ import annotations


def operation_index(document: dict) -> dict[str, dict]:
	"""Every operation of an OpenAPI document, keyed by operationId."""
	index = {}
	for path, methods in document["paths"].items():
		for verb, operation in methods.items():
			index[operation["operationId"]] = {"verb": verb, "path": path, **operation}

	return index


def search(index: dict[str, dict], query: str, limit: int = 10) -> list[dict]:
	"""Operations ranked by how many words of `query` their id, summary, description or tags hold."""
	words = query.lower().split()
	ranked = []
	for operation_id, entry in index.items():
		haystack = _haystack(operation_id, entry)
		score = sum(word in haystack for word in words) + sum(word in operation_id for word in words)
		if score:
			ranked.append((-score, operation_id))

	return [_hit(operation_id, index[operation_id]) for _, operation_id in sorted(ranked)[: max(1, limit)]]


def _hit(operation_id: str, entry: dict) -> dict:
	return {
		"operation": operation_id,
		"summary": entry.get("summary", ""),
		"description": entry.get("description", "").split("\n")[0],
		"changes_data": not entry["x-mcp"]["read_only"],
		"required": input_schema(entry)["required"],
	}


def _haystack(operation_id: str, entry: dict) -> str:
	return " ".join(
		[operation_id, entry.get("summary", ""), entry.get("description", ""), *(entry.get("tags") or [])]
	).lower()


def normalise(message):
	"""A tool result that reads as one block, whether the API answered with a list or an object."""
	if isinstance(message, list):
		return {"count": len(message), "results": message}

	return message


def keep_fields(message, fields: list[str]):
	"""Only `fields` of each record in the answer, so a large answer fits an agent's context."""
	if isinstance(message, list):
		return [_pick(row, fields) for row in message]
	if isinstance(message, dict):
		return {
			key: keep_fields(value, fields) if isinstance(value, list) else value
			for key, value in message.items()
		}

	return message


def first_record(message) -> dict:
	"""The first record of an answer that is a list, or that holds lists, else {}."""
	rows = message if isinstance(message, list) else []
	if isinstance(message, dict):
		rows = [row for value in message.values() if isinstance(value, list) for row in value]

	return next((row for row in rows if isinstance(row, dict)), {})


def _pick(row, fields: list[str]):
	return {key: row[key] for key in fields if key in row} if isinstance(row, dict) else row


def input_schema(entry: dict) -> dict:
	"""The JSON schema a tool caller fills in: path parameters plus the request body, one object."""
	properties, required = _parameters(entry)
	body = _body_schema(entry)
	properties.update(body.get("properties") or {})
	required.extend(body.get("required") or [])
	if entry.get("x-mcp", {}).get("requires_team") and "team" in properties:
		required.append("team")

	return {"type": "object", "properties": properties, "required": sorted(set(required))}


def _parameters(entry: dict) -> tuple[dict, list]:
	properties, required = {}, []
	for parameter in entry.get("parameters") or []:
		properties[parameter["name"]] = parameter.get("schema") or {}
		if parameter.get("required"):
			required.append(parameter["name"])

	return properties, required


def _body_schema(entry: dict) -> dict:
	return entry.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema") or {}


def validate(entry: dict, arguments: dict) -> str | None:
	"""The first problem with `arguments`, or None when they fit the schema."""
	schema = input_schema(entry)
	missing = [name for name in schema["required"] if not arguments.get(name)]
	if missing:
		return f"Missing required argument: {', '.join(missing)}"

	unknown = [name for name in arguments if name not in schema["properties"]]
	if unknown:
		return f"Unknown argument: {', '.join(unknown)}"

	return None


def build_request(entry: dict, arguments: dict) -> tuple[str, str, dict]:
	"""The HTTP call for one operation: method, path, and either query parameters or a JSON body."""
	path = entry["path"]
	query = {name: value for name, value in arguments.items() if f"{{{name}}}" in path}
	for name, value in query.items():
		path = path.replace(f"{{{name}}}", str(value))

	remaining = {name: value for name, value in arguments.items() if name not in query}
	if entry["verb"] == "get":
		return "GET", path, {"params": remaining}

	return "POST", path, {"json": remaining}
