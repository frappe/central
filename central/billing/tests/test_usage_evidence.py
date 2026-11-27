# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Each pushed line carries how its value was worked out; a day without it is kept and marked."""

import json

import frappe

from central.billing.revenue import usage_ledger, usage_month, usage_reports
from central.billing.revenue.service_reports import MAXIMUM_EVIDENCE
from central.billing.revenue.usage_month import bit
from central.billing.tests import test_usage_month
from central.billing.tests.test_ai_billing import TEAM_USD, AIBillingCase
from central.billing.tests.test_bundled_buckets import BundledServerFixture
from central.billing.tests.test_service_reports import GB, TEAM, ServiceReportsCase, line
from central.billing.tests.utils import BillingTestCase, ensure_team, usage_days
from central.services.doctype.service.service import STORAGE_EVIDENCE_KEYS


def evidence(gb: float, **values) -> dict:
	return {
		"v": 1,
		"peak": gb * GB,
		"peak_at": "2026-06-20T05:00:00Z",
		"readings": 3,
		"first": GB,
		"first_at": "2026-06-20T00:10:00Z",
		"last": gb * GB,
		"last_at": "2026-06-20T05:00:00Z",
		**values,
	}


def derived(day: str, gb: float, **values) -> dict:
	return {**line(day, gb), "evidence": evidence(gb, **values)}


class EvidenceCase(ServiceReportsCase):
	"""Pushed storage, whose meter names the keys each line's evidence carries."""

	def setUp(self):
		super().setUp()
		filters = {"parent": "storage", "meter_key": "bytes_stored"}
		before = frappe.db.get_value("Service Meter", filters, "evidence_keys")
		frappe.db.set_value("Service Meter", filters, "evidence_keys", STORAGE_EVIDENCE_KEYS)
		self.addCleanup(frappe.db.set_value, "Service Meter", filters, "evidence_keys", before)

	def underived_days(self) -> int:
		return frappe.db.get_value("Usage Month", {"team": TEAM}, "underived")


class TestPushedEvidence(EvidenceCase):
	def test_a_line_without_evidence_is_stored_and_marked(self):
		answer = self.send([line("2026-06-20", 10)])
		self.assertEqual(answer, {"accepted": 1, "rejected": [], "underived": 1})
		self.assertEqual(self.days(), [(frappe.utils.getdate("2026-06-20"), 10)])
		self.assertEqual(self.underived_days(), bit(20))

	def test_valid_evidence_leaves_the_day_derived(self):
		answer = self.send([derived("2026-06-19", 8), derived("2026-06-20", 10)])
		self.assertEqual(answer, {"accepted": 2, "rejected": [], "underived": 0})
		self.assertEqual(self.underived_days(), 0)

	def test_malformed_evidence_never_refuses_a_line(self):
		cases = {
			"2026-06-14": "not an object",
			"2026-06-15": {**evidence(1), "v": 0},
			"2026-06-16": {**evidence(1), "v": True},
			"2026-06-17": {**evidence(1), "v": "1"},
			"2026-06-18": {key: value for key, value in evidence(1).items() if key != "peak_at"},
		}
		answer = self.send([{**line(day, 1), "evidence": value} for day, value in cases.items()])
		self.assertEqual(answer, {"accepted": 5, "rejected": [], "underived": 5})
		self.assertEqual(self.underived_days(), sum(bit(day) for day in range(14, 19)))

	def test_evidence_over_the_limit_is_stored_without_a_derivation(self):
		large = derived("2026-06-20", 10, notes="x" * MAXIMUM_EVIDENCE)
		answer = self.send([large])
		self.assertEqual(answer, {"accepted": 1, "rejected": [], "underived": 1})
		self.assertEqual(self.days(), [(frappe.utils.getdate("2026-06-20"), 10)])
		self.assertEqual(self.underived_days(), bit(20))

	def test_a_higher_value_without_evidence_marks_the_day_again(self):
		self.send([derived("2026-06-20", 10)])
		self.send([line("2026-06-20", 12)], as_of="2026-06-20T06:32:00Z")
		self.assertEqual(self.days(), [(frappe.utils.getdate("2026-06-20"), 12)])
		self.assertEqual(self.underived_days(), bit(20))

	def test_a_lower_value_leaves_the_derivation_of_the_peak(self):
		self.send([derived("2026-06-20", 10)])
		self.send([line("2026-06-20", 9)], as_of="2026-06-20T06:32:00Z")
		self.assertEqual(self.underived_days(), 0)

	def test_evidence_is_kept_in_the_report_body_only(self):
		self.send([derived("2026-06-20", 10)])
		self.assertNotIn("evidence", frappe.db.get_value("Usage Month", {"team": TEAM}, "slots"))
		[day] = usage_days(team=TEAM)
		[kept] = json.loads(usage_reports.get_body(day.report))["lines"]
		self.assertEqual(kept["evidence"]["readings"], 3)


def kept_line(day) -> dict:
	"""The line of the report that set a stored day."""
	lines = json.loads(usage_reports.get_body(day.report))["lines"]
	return next(kept for kept in lines if str(kept["day"]) == str(day.day) and kept["subject"] == day.subject)


class TestCentralLineEvidence(BundledServerFixture, BillingTestCase):
	"""Central's own reads and estimates name how they got their value."""

	def setUp(self):
		self.set_up_bundled_server()

	def underived_days(self) -> int:
		return sum(frappe.get_all("Usage Month", filters={"subject": self.bucket}, pluck="underived"))

	def test_a_storage_read_names_what_cargo_answered(self):
		self.read("2026-06-01", 100)
		[day] = usage_days(subject=self.bucket)
		evidence = kept_line(day)["evidence"]
		self.assertEqual((evidence["read"], evidence["used_bytes"]), ("cargo.bucket_usage", 100 * GB))
		self.assertTrue(evidence["at"].endswith("Z"))
		self.assertEqual(self.underived_days(), 0)

	def test_an_estimate_names_the_day_it_copied(self):
		self.read("2026-06-01", 100)
		usage_ledger.fill_missing_days("2026-06-05")
		read, estimated = usage_days(subject=self.bucket)
		self.assertEqual(
			kept_line(estimated)["evidence"],
			{"v": 1, "estimate": {"copied_day": "2026-06-01", "report": read.report}},
		)
		self.assertEqual(self.underived_days(), 0)


class TestGroveReadEvidence(AIBillingCase):
	def test_a_grove_read_names_its_window_and_answer(self):
		self.land(TEAM_USD, "2026-06-10", {"claude-sonnet": 0.25})
		self.read("2026-06-10")
		[day] = self.days(TEAM_USD)
		evidence = kept_line(day)["evidence"]
		self.assertEqual(
			(evidence["read"], evidence["window"][0], evidence["requests"], evidence["tokens"]),
			("grove.usage", "2026-06-10T00:00:00Z", 1, 10),
		)
		self.assertEqual(len(evidence["sha256"]), 64)
		self.assertEqual(frappe.db.get_value("Usage Month", day.month_row, "underived"), 0)


class TestSegmentDays(BillingTestCase):
	def setUp(self):
		ensure_team(test_usage_month.TEAM)

	def test_a_segment_day_counts_as_derived(self):
		usage_month.write_lines([test_usage_month.line(3, 1, segment="segment-1")], None, "Segment")
		usage_month.write_lines([test_usage_month.line(4, 1)], "report-1", "Read By Central")
		underived = frappe.db.get_value("Usage Month", {"subject": test_usage_month.SUBJECT}, "underived")
		self.assertEqual(underived, bit(4))

	def test_an_estimate_replaced_by_a_line_without_evidence_marks_the_day(self):
		estimate = {"v": 1, "estimate": {"copied_day": "2026-06-02", "report": "report-1"}}
		usage_month.write_lines(
			[test_usage_month.line(3, 1, estimated=1, as_of=None, evidence=estimate)], None, "Estimated"
		)
		filters = {"subject": test_usage_month.SUBJECT}
		self.assertEqual(frappe.db.get_value("Usage Month", filters, "underived"), 0)
		usage_month.write_lines([test_usage_month.line(3, 2)], "report-2", "Pushed")
		self.assertEqual(frappe.db.get_value("Usage Month", filters, "underived"), bit(3))
