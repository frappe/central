# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Diffing across code with the inputs held fixed, rather than across time."""

import frappe

from central.billing.projection import cassette, engine
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-cassette"
CLUSTER = "ap-south-1"
PLAN = "bundle-cassette"
TODAY = "2026-08-06"


class TestRecording(IntegrationTestCase):
	def test_reads_are_captured_in_order(self):
		recorder = cassette.Recorder()
		recorder.record("a", 1)
		recorder.record("b", 2)
		recorder.record("a", 3)

		tape = recorder.cassette()
		self.assertEqual(tape["reads"], 3)
		self.assertEqual(tape["entries"]["a"], [1, 3])

	def test_a_key_is_stable_across_formatting(self):
		self.assertEqual(
			cassette.key("Invoice", {"team": "x", "status": "Open"}),
			cassette.key("Invoice", {"status": "Open", "team": "x"}),
		)

	def test_different_reads_get_different_keys(self):
		self.assertNotEqual(cassette.key("Invoice", "x"), cassette.key("Invoice", "y"))


class TestReplay(IntegrationTestCase):
	def test_a_recorded_read_is_answered_from_the_tape(self):
		recorder = cassette.Recorder()
		recorder.record("k", {"rate": 1000})
		replay = cassette.Replay(recorder.cassette())
		self.assertEqual(replay.answer("k"), {"rate": 1000})

	def test_repeated_reads_replay_in_the_order_they_were_captured(self):
		recorder = cassette.Recorder()
		recorder.record("k", 1)
		recorder.record("k", 2)
		replay = cassette.Replay(recorder.cassette())
		self.assertEqual(replay.answer("k"), 1)
		self.assertEqual(replay.answer("k"), 2)

	def test_a_read_the_tape_never_saw_is_reported_not_raised(self):
		# The code now consults something it did not before. That is a finding, and it is
		# often the explanation for whatever else moved.
		replay = cassette.Replay({"entries": {}})
		self.assertIsNone(replay.answer("new-read"))
		self.assertEqual(replay.missing, ["new-read"])


class TestDiffing(IntegrationTestCase):
	def test_an_identical_projection_produces_no_differences(self):
		before = {"invoice": {"total": 100.0, "lines": [{"amount": 100.0}]}}
		self.assertEqual(cassette.diff(before, dict(before)), [])

	def test_a_moved_number_is_found_with_its_path(self):
		out = cassette.diff({"invoice": {"total": 100.0}}, {"invoice": {"total": 120.0}})
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["path"], "invoice.total")
		self.assertEqual(out[0]["after"], 120.0)

	def test_offsetting_line_moves_are_not_hidden_by_a_matching_total(self):
		# The regression a summary comparison misses: the total is identical and two
		# lines moved in opposite directions.
		before = {"total": 100.0, "lines": [{"amount": 60.0}, {"amount": 40.0}]}
		after = {"total": 100.0, "lines": [{"amount": 40.0}, {"amount": 60.0}]}
		out = cassette.diff(before, after)
		self.assertEqual(len(out), 2)

	def test_a_float_wobble_is_not_a_regression(self):
		self.assertEqual(cassette.diff({"a": 100.0}, {"a": 100.000001}), [])

	def test_a_changed_line_count_is_reported_rather_than_compared_pairwise(self):
		out = cassette.diff({"lines": [1, 2]}, {"lines": [1]})
		self.assertEqual(out[0]["path"], "lines")

	def test_the_as_of_stamp_is_ignored_because_it_always_moves(self):
		self.assertEqual(cassette.diff({"as_of": "2026-01-01"}, {"as_of": "2026-06-01"}), [])

	def test_the_report_ranks_the_worst_money_move_first(self):
		out = cassette.report({"a": 100.0, "b": 100.0}, {"a": 101.0, "b": 500.0})
		self.assertTrue(out["changed"])
		self.assertEqual(out["worst"]["path"], "b")


class TestAgainstARealProjection(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 4000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()

	def test_the_same_code_on_the_same_data_diffs_to_nothing(self):
		first = engine.project(TEAM, "2026-09-01", "2026-09-30", today=TODAY)
		second = engine.project(TEAM, "2026-09-01", "2026-09-30", today=TODAY)
		self.assertFalse(cassette.report(first, second)["changed"])

	def test_a_real_change_in_the_data_shows_up_with_its_path(self):
		first = engine.project(TEAM, "2026-09-01", "2026-09-30", today=TODAY)
		add_segment(self.sub, "Plan Changed", 8000, "2026-09-16 00:00:00")
		frappe.db.commit()
		second = engine.project(TEAM, "2026-09-01", "2026-09-30", today=TODAY)

		out = cassette.report(first, second)
		self.assertTrue(out["changed"])
		self.assertTrue(any("total" in d["path"] for d in out["differences"]))

	def test_the_engine_accepts_the_recorder_and_source_seam(self):
		import inspect

		params = inspect.signature(engine.project).parameters
		self.assertIn("recorder", params)
		self.assertIn("source", params)
