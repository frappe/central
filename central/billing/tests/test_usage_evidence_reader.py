# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An operator traces a billed day to the signed report that set it and the derivation it carried."""

import hashlib

import frappe

from central.billing.api.admin.revenue import get_usage_day_evidence
from central.billing.revenue import usage_month, usage_reports
from central.billing.revenue.usage_evidence import NO_DERIVATION, DayEvidence
from central.billing.revenue.usage_month import bit
from central.billing.tests import test_usage_month
from central.billing.tests.test_service_reports import TEAM, line
from central.billing.tests.test_usage_evidence import EvidenceCase, derived, evidence
from central.billing.tests.utils import BillingTestCase, ensure_team, usage_days


class TestDayEvidence(EvidenceCase):
	def month_row(self) -> str:
		return frappe.db.get_value("Usage Month", {"team": TEAM}, "name")

	def test_a_day_names_its_signed_report_and_derivation(self):
		self.send([derived("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		[day] = usage_days(team=TEAM)
		report = found["report"]
		self.assertEqual((found["value"], found["source"], report["name"]), (10, "Pushed", day.report))
		self.assertEqual(report["sha256"], hashlib.sha256(usage_reports.get_body(day.report)).hexdigest())
		self.assertTrue(report["is_intact"])
		self.assertTrue(report["has_valid_signature"])
		self.assertEqual(found["line"]["value"], 10 * 1_000_000_000)
		self.assertEqual(found["derivation"], evidence(10))
		self.assertEqual(found["corrections"], [])

	def test_a_day_without_evidence_has_no_derivation(self):
		self.send([line("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual(found["line"]["value"], 10 * 1_000_000_000)
		self.assertEqual(found["derivation"], NO_DERIVATION)

	def test_evidence_that_was_refused_is_not_shown_as_a_derivation(self):
		self.send([{**line("2026-06-20", 10), "evidence": {"v": 1}}])
		self.assertEqual(DayEvidence.of(self.month_row(), 20)["derivation"], NO_DERIVATION)

	def test_of_two_lines_for_a_day_the_one_the_day_holds_is_found(self):
		self.send([derived("2026-06-20", 12), derived("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual((found["value"], found["derivation"]["peak"]), (12, 12 * 1_000_000_000))

	def test_a_correction_names_the_report_that_corrected_the_day(self):
		self.send([derived("2026-06-20", 10)])
		usage_month.stamp_days({self.month_row(): bit(20)}, "invoice-evidence")
		self.send([derived("2026-06-20", 14)], as_of="2026-06-20T06:32:00Z")
		found = DayEvidence.of(self.month_row(), 20)
		[correction] = found["corrections"]
		self.assertEqual((found["value"], correction["value"], correction["status"]), (10, 14, "Open"))
		self.assertNotEqual(correction["report"]["name"], found["report"]["name"])
		self.assertEqual(correction["derivation"]["peak"], 14 * 1_000_000_000)

	def test_a_day_with_no_value_is_refused(self):
		self.send([line("2026-06-20", 10)])
		with self.assertRaises(frappe.ValidationError):
			DayEvidence.of(self.month_row(), 19)

	def test_only_an_operator_may_read_the_evidence(self):
		self.send([line("2026-06-20", 10)])
		name = self.month_row()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			get_usage_day_evidence(name, 20)
		frappe.set_user("Administrator")
		self.assertEqual(get_usage_day_evidence(name, 20)["value"], 10)


class TestSegmentDayEvidence(BillingTestCase):
	def setUp(self):
		ensure_team(test_usage_month.TEAM)

	def test_a_segment_day_names_its_segment(self):
		usage_month.write_lines([test_usage_month.line(3, 1, segment="segment-1")], None, "Segment")
		name = frappe.db.get_value("Usage Month", {"subject": test_usage_month.SUBJECT}, "name")
		found = DayEvidence.of(name, 3)
		self.assertEqual((found["report"], found["derivation"]), (None, {"segment": "segment-1"}))
