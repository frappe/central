import importlib
import inspect
import types
import typing

import frappe

from central import __version__

# Opt in: only these endpoints are public. The console's own flows (trial signup, onboarding,
# uploads, search-as-you-type) and staff actions stay out until someone adds them here on purpose.
PUBLIC_API = {
	"identity": (
		"Identity",
		"The signed-in user: profile, teams, invitations and capabilities.",
		("my_capabilities", "my_invitations", "my_profile", "my_teams", "update_profile"),
	),
	"teams": (
		"Teams",
		"Team settings, members, roles and invitations.",
		(
			"accept_invitation",
			"archive_team",
			"create_custom_role",
			"create_team",
			"decline_invitation",
			"delete_custom_role",
			"get_team_archive_checks",
			"invite_team_member",
			"leave_team",
			"list_team_members",
			"list_team_roles",
			"remove_team_member",
			"rename_team",
			"resend_invitation",
			"revoke_invitation",
			"set_team_member_roles",
			"set_team_member_status",
			"transfer_team_ownership",
		),
	),
	"servers": (
		"Servers",
		"Create, size, power and protect servers.",
		(
			"action_status",
			"create_composed_server",
			"create_server",
			"get_rescue_state",
			"list_instances",
			"open_console",
			"public_ipv4_pricing",
			"registry",
			"rename_server",
			"resize_server",
			"restart_server",
			"retry_action",
			"server_hostnames",
			"server_metrics",
			"server_overview",
			"set_rescue_mode",
			"set_server_ipv4_internet",
			"set_server_public_ip",
			"set_server_wireguard_access",
			"set_termination_protection",
			"start_server",
			"stop_server",
			"terminate_server",
			"update_server_firewall",
		),
	),
	"images": (
		"Images",
		"Offerings, images and apps a new server can start from.",
		("eligible_plans", "get_app_requirements", "list_apps", "list_images", "list_offerings"),
	),
	"snapshots": (
		"Snapshots",
		"Server snapshots and their schedules.",
		(
			"delete_snapshots",
			"keep_snapshot",
			"list_snapshots",
			"set_automatic_snapshots",
			"snapshot_pricing",
			"take_snapshot",
		),
	),
	"firewall_rulesets": (
		"Firewall Rulesets",
		"Team firewall rules and the servers that use them.",
		(
			"delete_firewall_ruleset",
			"list_firewall_rulesets",
			"save_firewall_ruleset",
			"set_server_firewall_rulesets",
		),
	),
	"ssh_keys": (
		"SSH Keys",
		"Team SSH keys and the servers they reach.",
		(
			"create_team_ssh_key",
			"delete_team_ssh_key",
			"list_team_ssh_keys",
			"retry_team_ssh_key_sync",
			"rotate_team_ssh_key",
			"set_server_ssh_keys",
		),
	),
	"wireguard": (
		"WireGuard",
		"Devices that reach team servers through the regional gateway.",
		("create_wireguard_device", "delete_wireguard_device", "list_wireguard_devices"),
	),
	"activity": (
		"Activity",
		"What happened on a team and its servers, newest first.",
		("server_activity", "team_activity"),
	),
	"support": (
		"Support",
		"Support tickets.",
		("create_ticket", "get_ticket_options", "list_tickets"),
	),
}

_DESCRIPTION = (
	"Central is the control plane for Frappe Cloud v2. It owns identity, teams, servers, "
	"sites and billing. Send `Authorization: token <api key>:<api secret>` and "
	"`Frappe-Authorization-Source: API Key`. "
	"A key acts on one team, within its permissions and its user's role."
)

_SCHEMA_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}

_ERROR_RESPONSES = {
	"401": {"description": "Missing or invalid API key"},
	"403": {"description": "The token user lacks the capability"},
}

_READ_ONLY_NOTE = "Read-only."
_CHANGES_DATA_NOTE = "Changes data."


def build_document() -> dict:
	paths, models = {}, {}
	for module_name, (_title, _about, names) in PUBLIC_API.items():
		module = importlib.import_module(f"central.api.{module_name}")
		for function, hints in _public_functions(module, names):
			path = f"/api/method/{module.__name__}.{function.__name__}"
			paths[path] = {_http_method(function): _operation(module_name, function, hints, models)}

	return {
		"openapi": "3.1.0",
		"info": {
			"title": "Central API",
			"version": __version__,
			"description": _DESCRIPTION,
		},
		"components": {
			"securitySchemes": {
				"apiKey": {
					"type": "apiKey",
					"in": "header",
					"name": "Authorization",
					"description": (
						"`token <api key>:<api secret>`, sent with `Frappe-Authorization-Source: API Key`. "
						"The key's team and permissions, within its user's role, apply."
					),
				}
			},
			"schemas": {name: schema for name, (_model, schema) in sorted(models.items())},
		},
		"security": [{"apiKey": []}],
		"tags": [{"name": title, "description": about} for title, about, _names in PUBLIC_API.values()],
		"paths": dict(sorted(paths.items())),
	}


def _public_functions(module, names: tuple[str, ...]) -> typing.Iterator[tuple[typing.Callable, dict]]:
	"""Each listed function. A name that is not a logged-in endpoint answering JSON fails the build."""
	for name in names:
		function = getattr(module, name)
		if function not in frappe.whitelisted or function in frappe.guest_methods:
			raise TypeError(f"{module.__name__}.{name} is not a logged-in endpoint.")

		hints = _type_hints(function)
		if not _is_json_return(hints.get("return", inspect.Signature.empty)):
			raise TypeError(f"{module.__name__}.{name} does not answer JSON.")

		yield function, hints


def _is_json_return(annotation) -> bool:
	"""A handler that returns no body still answers JSON, so it belongs in the document."""
	if annotation in (None, type(None)):
		return True

	return bool(_schema(annotation, {}))


def _type_hints(function) -> dict:
	try:
		return typing.get_type_hints(function)
	except (NameError, TypeError):
		# A hint naming a type only imported under TYPE_CHECKING cannot resolve at runtime.
		return dict(function.__annotations__)


def _http_method(function) -> str:
	methods = frappe.allowed_http_methods_for_whitelisted_func.get(function, ())
	return "get" if "GET" in methods else "post"


def _operation(module_name: str, function, hints: dict, models: dict) -> dict:
	properties, required = _arguments(function, hints, models)
	method = _http_method(function)
	docstring = inspect.getdoc(function) or ""
	summary = function.__name__.replace("_", " ").capitalize()
	note = _READ_ONLY_NOTE if method == "get" else _CHANGES_DATA_NOTE
	operation = {
		"operationId": f"{module_name}.{function.__name__}",
		"tags": [PUBLIC_API[module_name][0]],
		"summary": summary,
		"description": f"{docstring or summary}\n\n{note}",
		"deprecated": False,
		"responses": _responses(hints.get("return"), models),
	}
	operation.update(_payload(method, properties, required, _request_model_name(function), models))

	return operation


def _responses(answer, models: dict) -> dict:
	"""Frappe wraps the return value in `message`, and leaves it out when the function returns None."""
	ok = {"description": "OK"}
	if answer not in (None, type(None)):
		message = {
			"type": "object",
			"properties": {"message": _answer_schema(answer, models)},
			"required": ["message"],
		}
		ok["content"] = {"application/json": {"schema": message}}

	return {"200": ok, **_ERROR_RESPONSES}


def _answer_schema(answer, models: dict) -> dict:
	"""A returned union is one of its types; only an argument's `str` member is a form fallback."""
	members = typing.get_args(answer) if typing.get_origin(answer) in (typing.Union, types.UnionType) else ()
	if len([member for member in members if member is not type(None)]) < 2:
		return _schema(answer, models)

	return {"anyOf": [_schema(member, models) or {"type": "null"} for member in members]}


def _request_model_name(function) -> str:
	return "".join(word.capitalize() for word in function.__name__.split("_")) + "Request"


def _arguments(function, hints: dict, models: dict) -> tuple[dict, list]:
	properties, required = {}, []
	for name, parameter in inspect.signature(function).parameters.items():
		if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
			continue
		properties[name] = _schema(hints.get(name, parameter.annotation), models)
		if parameter.default is inspect.Parameter.empty:
			required.append(name)

	return properties, required


def _payload(method: str, properties: dict, required: list, name: str, models: dict) -> dict:
	if method == "get":
		return {
			"parameters": [
				{"name": name, "in": "query", "required": name in required, "schema": properties[name]}
				for name in properties
			]
		}

	schema = {"type": "object", "properties": properties}
	if required:
		schema["required"] = required
	_add_model(models, name, name, schema)

	return {"requestBody": {"content": {"application/json": {"schema": _reference(name)}}}}


def _schema(annotation, models: dict) -> dict:
	"""The JSON schema of a type hint, or `{}` for a missing hint or `Any`."""
	if typing.is_typeddict(annotation):
		return _model_schema(annotation, models)

	origin = typing.get_origin(annotation) or annotation
	arguments = typing.get_args(annotation)
	if origin in (typing.Union, types.UnionType):
		return _union_schema(arguments, models)
	if origin is typing.Literal:
		return {"type": "string", "enum": list(arguments)}
	if origin in (list, tuple):
		return _array_schema(arguments, models)
	if origin is dict:
		return _mapping_schema(arguments, models)

	return {"type": _SCHEMA_TYPES[annotation]} if annotation in _SCHEMA_TYPES else {}


def _array_schema(arguments: tuple, models: dict) -> dict:
	schema = {"type": "array"}
	if arguments and arguments[0] is not Ellipsis:
		items = _schema(arguments[0], models)
		if items:
			schema["items"] = items

	return schema


def _union_schema(arguments: tuple, models: dict) -> dict:
	# `str` beside another type is the form-encoded fallback; a JSON caller sends the other type.
	members = [member for member in arguments if member not in (str, type(None))] or [str]
	schema = _schema(members[0], models)
	if schema and type(None) in arguments:
		return _nullable(schema)

	return schema


def _nullable(schema: dict) -> dict:
	if "type" in schema:
		return {**schema, "type": [schema["type"], "null"]}

	return {"anyOf": [schema, {"type": "null"}]}


def _mapping_schema(arguments: tuple, models: dict) -> dict:
	values = _schema(arguments[1], models) if len(arguments) == 2 else {}
	return {"type": "object", "additionalProperties": values} if values else {"type": "object"}


def _model_schema(model, models: dict) -> dict:
	"""A reference to `model`, a TypedDict, whose schema is added to `models` the first time."""
	name = model.__name__
	if name not in models:
		_add_model(models, name, model, {})
		hints = typing.get_type_hints(model)
		schema = {"type": "object", "properties": {key: _schema(hint, models) for key, hint in hints.items()}}
		if model.__required_keys__:
			schema["required"] = sorted(model.__required_keys__)
		if model.__doc__:
			schema["description"] = inspect.cleandoc(model.__doc__)
		models[name] = (model, schema)
	elif models[name][0] is not model:
		raise TypeError(f"Two response models are named {name}.")

	return _reference(name)


def _add_model(models: dict, name: str, owner, schema: dict) -> None:
	if name in models and models[name][0] is not owner:
		raise TypeError(f"Two models are named {name}.")
	models[name] = (owner, schema)


def _reference(name: str) -> dict:
	return {"$ref": f"#/components/schemas/{name}"}


@frappe.whitelist(methods=["GET"])
def document() -> dict:
	"""The OpenAPI document for the caller. The docs page reads the same file from the assets."""
	return build_document()
