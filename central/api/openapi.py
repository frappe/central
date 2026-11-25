import importlib
import inspect
import types
import typing

import frappe

from central import __version__

# Module, the name the reference shows, and what the group covers.
DOCUMENTED_MODULES = {
	"identity": ("Identity", "The signed-in user: profile, teams, invitations and capabilities."),
	"teams": ("Teams", "Team settings, members, roles and invitations."),
	"servers": ("Servers", "Create, size, power and protect servers."),
	"sites": ("Sites", "Sites on a team's servers."),
	"images": ("Images", "Offerings, images and apps a new server can start from."),
	"snapshots": ("Snapshots", "Server snapshots and their schedules."),
	"firewall_rulesets": ("Firewall Rulesets", "Team firewall rules and the servers that use them."),
	"ssh_keys": ("SSH Keys", "Team SSH keys and the servers they reach."),
	"wireguard": ("WireGuard", "Devices that reach team servers through the regional gateway."),
	"activity": ("Activity", "What happened on a team and its servers, newest first."),
	"support": ("Support", "Support tickets and help articles."),
}

_DESCRIPTION = (
	"Central is the control plane for Frappe Cloud v2. It owns identity, teams, servers, "
	"sites and billing. Send the header `Authorization: token <api key>:<api secret>`. "
	"The capabilities of the token's user decide access."
)

_SCHEMA_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}

_RESPONSES = {
	"200": {
		"description": "OK",
		"content": {"application/json": {"schema": {"type": "object", "properties": {"message": {}}}}},
	},
	"401": {"description": "Missing or invalid API key"},
	"403": {"description": "The token user lacks the capability"},
}

_READ_ONLY_NOTE = "Read-only."
_CHANGES_DATA_NOTE = "Changes data."


def build_document() -> dict:
	paths = {}
	for module_name in DOCUMENTED_MODULES:
		module = importlib.import_module(f"central.api.{module_name}")
		for function, hints in _documented_functions(module):
			path = f"/api/method/{module.__name__}.{function.__name__}"
			paths[path] = {_http_method(function): _operation(module_name, function, hints)}

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
					"description": ("`token <api key>:<api secret>`. The caller's own capabilities apply."),
				}
			}
		},
		"security": [{"apiKey": []}],
		"tags": [{"name": name, "description": about} for name, about in DOCUMENTED_MODULES.values()],
		"paths": dict(sorted(paths.items())),
	}


def _documented_functions(module) -> typing.Iterator[tuple[typing.Callable, dict]]:
	"""Each whitelisted non-guest function this module defines and returns JSON."""
	for value in vars(module).values():
		if not inspect.isfunction(value) or value.__module__ != module.__name__:
			continue
		if value not in frappe.whitelisted or value in frappe.guest_methods:
			continue

		hints = _type_hints(value)
		if _is_json_return(hints.get("return", inspect.Signature.empty)):
			yield value, hints


def _is_json_return(annotation) -> bool:
	"""A handler that returns no body still answers JSON, so it belongs in the document."""
	if annotation in (None, type(None)):
		return True

	return bool(_schema(annotation))


def _type_hints(function) -> dict:
	try:
		return typing.get_type_hints(function)
	except (NameError, TypeError):
		# A hint naming a type only imported under TYPE_CHECKING cannot resolve at runtime.
		return dict(function.__annotations__)


def _http_method(function) -> str:
	methods = frappe.allowed_http_methods_for_whitelisted_func.get(function, ())
	return "get" if "GET" in methods else "post"


def _operation(module_name: str, function, hints: dict) -> dict:
	properties, required = _arguments(function, hints)
	method = _http_method(function)
	docstring = inspect.getdoc(function) or ""
	summary = function.__name__.replace("_", " ").capitalize()
	note = _READ_ONLY_NOTE if method == "get" else _CHANGES_DATA_NOTE
	operation = {
		"operationId": f"{module_name}.{function.__name__}",
		"tags": [DOCUMENTED_MODULES[module_name][0]],
		"summary": summary,
		"description": f"{docstring or summary}\n\n{note}",
		"deprecated": False,
		"responses": _RESPONSES,
		"x-mcp": {"requires_team": "team" in properties, "read_only": method == "get"},
	}
	operation.update(_payload(method, properties, required))

	return operation


def _arguments(function, hints: dict) -> tuple[dict, list]:
	properties, required = {}, []
	for name, parameter in inspect.signature(function).parameters.items():
		if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
			continue
		properties[name] = _schema(hints.get(name, parameter.annotation))
		if parameter.default is inspect.Parameter.empty:
			required.append(name)

	return properties, required


def _payload(method: str, properties: dict, required: list) -> dict:
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

	return {"requestBody": {"content": {"application/json": {"schema": schema}}}}


def _schema(annotation) -> dict:
	"""The JSON schema of a type hint, or `{}` for a missing hint or `Any`."""
	origin = typing.get_origin(annotation) or annotation
	arguments = typing.get_args(annotation)
	if origin in (typing.Union, types.UnionType):
		return _union_schema(arguments)
	if origin is typing.Literal:
		return {"type": "string", "enum": list(arguments)}
	if origin in (list, tuple):
		return _array_schema(arguments)
	if origin is dict:
		return {"type": "object"}

	return {"type": _SCHEMA_TYPES[annotation]} if annotation in _SCHEMA_TYPES else {}


def _array_schema(arguments: tuple) -> dict:
	schema = {"type": "array"}
	if arguments and arguments[0] is not Ellipsis:
		items = _schema(arguments[0])
		if items:
			schema["items"] = items

	return schema


def _union_schema(arguments: tuple) -> dict:
	# `str` beside another type is the form-encoded fallback; a JSON caller sends the other type.
	members = [member for member in arguments if member not in (str, type(None))] or [str]
	schema = _schema(members[0])
	if schema and type(None) in arguments:
		schema["type"] = [schema["type"], "null"]

	return schema


@frappe.whitelist(methods=["GET"])
def document() -> dict:
	"""The OpenAPI document for the caller. The docs page reads the same file from the assets."""
	return build_document()
