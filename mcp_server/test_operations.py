import json
import unittest
from pathlib import Path

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

SPEC = Path(__file__).resolve().parents[1] / "central" / "public" / "openapi.json"


class TestOperations(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.index = operation_index(json.loads(SPEC.read_text()))

	def test_every_operation_is_indexed_once(self):
		self.assertGreaterEqual(len(self.index), 90)

	def test_search_matches_an_id_and_a_tag(self):
		self.assertIn(
			"teams.list_team_members",
			[hit["operation"] for hit in search(self.index, "list_team_members")],
		)
		self.assertTrue(search(self.index, "support"))

	def test_a_team_operation_requires_the_team(self):
		schema = input_schema(self.index["teams.list_team_members"])
		self.assertIn("team", schema["required"])
		self.assertEqual(
			validate(self.index["teams.list_team_members"], {}), "Missing required argument: team"
		)

	def test_an_unknown_argument_is_reported(self):
		problem = validate(self.index["teams.list_team_members"], {"team": "TEAM-1", "colour": "red"})
		self.assertEqual(problem, "Unknown argument: colour")

	def test_a_get_call_becomes_query_parameters_and_a_post_a_body(self):
		verb, path, request = build_request(self.index["teams.list_team_members"], {"team": "TEAM-1"})
		self.assertEqual(
			(verb, path, request),
			("GET", "/api/method/central.api.teams.list_team_members", {"params": {"team": "TEAM-1"}}),
		)

		verb, path, request = build_request(
			self.index["support.create_ticket"],
			{
				"team": "TEAM-1",
				"category": "server",
				"issue_type": "Unreachable or down",
				"description": "Down.",
			},
		)
		self.assertEqual(verb, "POST")
		self.assertEqual(request["json"]["team"], "TEAM-1")

	def test_multi_word_search_matches_description_words(self):
		hits = [hit["operation"] for hit in search(self.index, "team members")]
		self.assertIn("teams.list_team_members", hits)

	def test_a_partial_match_ranks_below_a_full_one(self):
		hits = [hit["operation"] for hit in search(self.index, "support ticket categories issue types")]
		self.assertEqual(hits[0], "support.get_ticket_options")

	def test_fields_trim_records_in_lists_and_in_objects(self):
		self.assertEqual(keep_fields([{"a": 1, "b": 2}], ["a"]), [{"a": 1}])
		self.assertEqual(
			keep_fields({"rows": [{"a": 1, "b": 2}], "n": 1}, ["a"]), {"rows": [{"a": 1}], "n": 1}
		)

	def test_first_record_looks_inside_lists_and_objects(self):
		self.assertEqual(first_record({"rows": [{"a": 1}], "n": 1}), {"a": 1})
		self.assertEqual(first_record({"n": 1}), {})

	def test_a_list_answer_reads_as_one_result(self):
		self.assertEqual(normalise([1, 2]), {"count": 2, "results": [1, 2]})
		self.assertEqual(normalise({"a": 1}), {"a": 1})

	def test_a_read_only_operation_is_marked(self):
		self.assertTrue(self.index["teams.list_team_members"]["x-mcp"]["read_only"])
		self.assertFalse(self.index["support.create_ticket"]["x-mcp"]["read_only"])


if __name__ == "__main__":
	unittest.main()
