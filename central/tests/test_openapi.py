import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from central.api.openapi import build_document, document

SPEC = Path(__file__).resolve().parents[2] / "central" / "public" / "openapi.json"


def _request_properties(document: dict, operation: dict) -> dict:
	body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
	if not body:
		return {}

	name = body["schema"]["$ref"].rsplit("/", 1)[1]
	return document["components"]["schemas"][name]["properties"]


def _declared_names(document: dict, operation: dict) -> set:
	names = {parameter["name"] for parameter in operation.get("parameters", [])}
	return names | set(_request_properties(document, operation))


def _is_named_model(schema: dict) -> bool:
	"""A model, a list of models, a mapping or a scalar: anything but a bare object."""
	if "anyOf" in schema:
		return all(_is_named_model(member) for member in schema["anyOf"])
	item = schema.get("items", {}) if schema.get("type") == "array" else schema

	return "$ref" in item or "additionalProperties" in item or item.get("type") not in (None, "object")


class TestOpenAPI(IntegrationTestCase):
	def test_committed_file_matches_the_document(self):
		self.assertEqual(json.loads(SPEC.read_text()), build_document())

	def test_the_endpoint_serves_the_committed_file(self):
		self.assertEqual(json.loads(SPEC.read_text()), document())

	def test_no_path_comes_from_a_guest_method(self):
		for path in build_document()["paths"]:
			function = frappe.get_attr(path.removeprefix("/api/method/"))
			self.assertNotIn(function, frappe.guest_methods, path)

	def test_every_operation_is_documented_and_identified(self):
		operation_ids = set()
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				self.assertTrue(operation["summary"], path)
				self.assertTrue(operation["description"], path)
				self.assertNotIn(operation["operationId"], operation_ids, path)
				operation_ids.add(operation["operationId"])

	def test_every_operation_declares_the_shared_response_codes(self):
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				responses = operation["responses"]
				self.assertEqual({"200", "401", "403"}, set(responses), path)
				self.assertEqual("OK", responses["200"]["description"], path)

	def test_every_response_and_request_is_a_named_model(self):
		document = build_document()
		for path, methods in document["paths"].items():
			for operation in methods.values():
				content = operation["responses"]["200"].get("content")
				if content:
					message = content["application/json"]["schema"]["properties"]["message"]
					self.assertTrue(_is_named_model(message), path)
				body = operation.get("requestBody")
				if body:
					self.assertIn("$ref", body["content"]["application/json"]["schema"], path)

	def test_every_operation_declares_its_mcp_behavior(self):
		for path, methods in build_document()["paths"].items():
			for method, operation in methods.items():
				self.assertEqual({"requires_team", "read_only"}, set(operation["x-mcp"]), path)
				self.assertEqual(method == "get", operation["x-mcp"]["read_only"], path)

	def test_every_description_ends_with_its_data_change_note(self):
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				description = operation["description"]
				self.assertTrue(description.endswith(("Read-only.", "Changes data.")), path)
				self.assertGreater(len(description), len("Changes data.") + 1, path)

	def test_requires_team_matches_a_declared_team_parameter(self):
		requires_team = 0
		declares_team = 0
		document = build_document()
		for path, methods in document["paths"].items():
			for operation in methods.values():
				names = _declared_names(document, operation)
				counted = operation["x-mcp"]["requires_team"]
				requires_team += counted
				declares_team += "team" in names
				self.assertEqual("team" in names, counted, path)

		self.assertEqual(requires_team, declares_team)
		self.assertGreater(requires_team, 0)

	def test_the_document_has_the_expected_size(self):
		count = sum(len(methods) for methods in build_document()["paths"].values())
		self.assertGreaterEqual(count, 60)

	def test_every_argument_has_a_type(self):
		document = build_document()
		for path, methods in document["paths"].items():
			for operation in methods.values():
				schemas = [parameter["schema"] for parameter in operation.get("parameters", [])]
				schemas += _request_properties(document, operation).values()
				self.assertNotIn({}, schemas, path)

	def test_operator_actions_stay_out_of_the_document(self):
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				self.assertFalse(operation["description"].startswith("Operator action"), path)
