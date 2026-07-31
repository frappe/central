# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing counters are emitted, and emitted as parseable JSON."""

import json
from unittest.mock import patch

from central.billing.platform import metrics
from central.billing.tests.utils import BillingTestCase


class _Captured:
	"""Stands in for the billing logger and keeps what was written."""

	def __init__(self):
		self.lines = []

	def info(self, line):
		self.lines.append(line)

	def records(self):
		return [json.loads(line) for line in self.lines]


class TestMetrics(BillingTestCase):
	def setUp(self):
		self.log = _Captured()
		patcher = patch.object(metrics.frappe, "logger", return_value=self.log)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_emit_writes_one_json_line(self):
		metrics.emit("billing.draft_page", drafted=3, failed=0)
		self.assertEqual(
			self.log.records(),
			[{"metric": "billing.draft_page", "drafted": 3, "failed": 0}],
		)

	def test_non_serialisable_values_do_not_break_the_line(self):
		import datetime

		metrics.emit("billing.run_status", period_end=datetime.date(2026, 6, 30))
		self.assertEqual(self.log.records()[0]["period_end"], "2026-06-30")

	def test_timed_reports_duration_and_the_counters_set_in_the_block(self):
		with metrics.timed("billing.settle_page", cutoff="2026-06-30") as counters:
			counters["settled"] = 2

		record = self.log.records()[0]
		self.assertEqual(record["metric"], "billing.settle_page")
		self.assertEqual(record["settled"], 2)
		self.assertEqual(record["outcome"], "ok")
		self.assertGreaterEqual(record["duration_ms"], 0)

	def test_a_block_that_raises_still_emits_and_says_so(self):
		with self.assertRaises(ValueError), metrics.timed("billing.draft_page") as counters:
			counters["drafted"] = 1
			raise ValueError("boom")

		record = self.log.records()[0]
		self.assertEqual(record["outcome"], "error")
		self.assertEqual(record["drafted"], 1)
