import json
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from central.api.openapi import build_document, document

SPEC = Path(__file__).resolve().parents[2] / "central" / "public" / "openapi.json"


def _declared_names(operation: dict) -> set:
	names = {parameter["name"] for parameter in operation.get("parameters", [])}
	body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
	return names | set(body.get("schema", {}).get("properties", {}))


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
				self.assertEqual(
					{"type": "object", "properties": {"message": {}}},
					responses["200"]["content"]["application/json"]["schema"],
					path,
				)

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
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				names = _declared_names(operation)
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
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				schemas = [parameter["schema"] for parameter in operation.get("parameters", [])]
				body = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
				schemas += body.get("schema", {}).get("properties", {}).values()
				self.assertNotIn({}, schemas, path)

	def test_operator_actions_stay_out_of_the_document(self):
		for path, methods in build_document()["paths"].items():
			for operation in methods.values():
				self.assertFalse(operation["description"].startswith("Operator action"), path)
