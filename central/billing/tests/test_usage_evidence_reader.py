# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An operator traces a billed day to the signed report that set it and the derivation it carried."""

import datetime
import hashlib
from unittest.mock import patch

import frappe

from central.billing.api.admin.revenue import get_usage_day_evidence
from central.billing.revenue import usage_month, usage_reports
from central.billing.revenue.usage_evidence import DayEvidence, check_days_carry_a_derivation
from central.billing.revenue.usage_month import bit
from central.billing.tests import test_usage_month
from central.billing.tests.test_service_reports import TEAM, line
from central.billing.tests.test_usage_evidence import EvidenceCase, derived, evidence
from central.billing.tests.utils import BillingTestCase, ensure_team, usage_days
from central.patches.v0_0 import count_underived_days_from_now, mark_derived_usage_corrections
from central.services.doctype.service.service import Service

SERVICES = ("evidence-check-storage", "evidence-check-ai")
REPORT_KEYS = {
	"name",
	"service",
	"kind",
	"received_at",
	"as_of",
	"sha256",
	"is_kept",
	"is_intact",
	"has_valid_signature",
}
NONE = {"kind": "None"}
UNRECORDED = {"kind": "Unrecorded"}


class TestDayEvidence(EvidenceCase):
	def month_row(self) -> str:
		return frappe.db.get_value("Usage Month", {"team": TEAM}, "name")

	def test_a_day_names_its_signed_report_and_derivation(self):
		self.send([derived("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		[day] = usage_days(team=TEAM)
		report = found["report"]
		self.assertEqual(set(report), REPORT_KEYS)
		self.assertEqual((found["value"], found["source"], report["name"]), (10, "Pushed", day.report))
		self.assertEqual(report["sha256"], hashlib.sha256(usage_reports.get_body(day.report)).hexdigest())
		self.assertTrue(report["is_intact"])
		self.assertTrue(report["has_valid_signature"])
		self.assertEqual(found["line"]["value"], 10 * 1_000_000_000)
		self.assertTrue(found["derived"])
		self.assertEqual(found["derivation"], {"kind": "Evidence", "evidence": evidence(10)})
		self.assertEqual(found["corrections"], [])

	def test_a_day_without_evidence_has_no_derivation(self):
		self.send([line("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual(found["line"]["value"], 10 * 1_000_000_000)
		self.assertEqual((found["derived"], found["derivation"]), (False, NONE))

	def test_evidence_that_was_refused_is_not_shown_as_a_derivation(self):
		self.send([{**line("2026-06-20", 10), "evidence": {"v": 1}}])
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual((found["derived"], found["derivation"]), (False, NONE))
		self.assertEqual(found["line"]["evidence"], {"v": 1})

	def test_the_verdict_kept_on_receipt_stays_when_the_meter_keys_change(self):
		self.send([derived("2026-06-20", 10)])
		self.send([line("2026-06-21", 10)])
		filters = {"parent": "storage", "meter_key": "bytes_stored"}
		frappe.db.set_value("Service Meter", filters, "evidence_keys", "peak,missing")
		self.assertEqual(DayEvidence.of(self.month_row(), 20)["derivation"]["kind"], "Evidence")
		self.assertEqual(DayEvidence.of(self.month_row(), 21)["derivation"], NONE)

	def test_of_two_lines_for_a_day_the_one_the_day_holds_is_found(self):
		self.send([derived("2026-06-20", 12), derived("2026-06-20", 10)])
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual((found["value"], found["derivation"]["evidence"]["peak"]), (12, 12 * 1_000_000_000))

	def test_a_correction_names_the_report_that_corrected_the_day(self):
		self.send([derived("2026-06-20", 10)])
		usage_month.stamp_days({self.month_row(): bit(20)}, "invoice-evidence")
		self.send([derived("2026-06-20", 14)], as_of="2026-06-20T06:32:00Z")
		found = DayEvidence.of(self.month_row(), 20)
		[correction] = found["corrections"]
		self.assertEqual((found["value"], correction["value"], correction["status"]), (10, 14, "Open"))
		self.assertNotEqual(correction["report"]["name"], found["report"]["name"])
		self.assertEqual(set(correction["report"]), REPORT_KEYS)
		self.assertTrue(correction["derived"])
		self.assertEqual(correction["derivation"]["evidence"]["peak"], 14 * 1_000_000_000)

	def test_a_correction_without_evidence_keeps_its_verdict(self):
		self.send([derived("2026-06-20", 10)])
		usage_month.stamp_days({self.month_row(): bit(20)}, "invoice-evidence")
		self.send([line("2026-06-20", 14)], as_of="2026-06-20T06:32:00Z")
		[correction] = DayEvidence.of(self.month_row(), 20)["corrections"]
		self.assertEqual((correction["derived"], correction["derivation"]), (False, NONE))
		self.assertEqual(
			frappe.db.get_value("Usage Month Correction", {"parent": self.month_row()}, "derived"), 0
		)

	def test_a_correction_kept_before_the_verdict_reads_unrecorded(self):
		self.send([derived("2026-06-20", 10)])
		usage_month.stamp_days({self.month_row(): bit(20)}, "invoice-evidence")
		self.send([line("2026-06-20", 14)], as_of="2026-06-20T06:32:00Z")
		mark_derived_usage_corrections.execute()
		[correction] = DayEvidence.of(self.month_row(), 20)["corrections"]
		self.assertEqual((correction["derived"], correction["derivation"]), (True, UNRECORDED))

	def test_a_day_stored_before_the_verdict_reads_unrecorded(self):
		self.send([line("2026-06-20", 10)])
		count_underived_days_from_now.execute()
		found = DayEvidence.of(self.month_row(), 20)
		self.assertEqual((found["derived"], found["derivation"]), (True, UNRECORDED))

	def test_a_day_whose_body_is_no_longer_kept_reads_unrecorded(self):
		self.send([derived("2026-06-20", 10)])
		[day] = usage_days(team=TEAM)
		frappe.db.set_value("Usage Report", day.report, "body", None)
		found = DayEvidence.of(self.month_row(), 20)
		self.assertFalse(found["report"]["is_kept"])
		self.assertEqual((found["line"], found["derived"], found["derivation"]), (None, True, UNRECORDED))

	def test_a_day_of_a_meter_removed_from_its_service_still_answers(self):
		self.send([derived("2026-06-20", 10)])
		# Patched, not deleted: saving the Service in teardown would keep a deleted meter deleted.
		with patch.object(Service, "get_meter", return_value=None):
			found = get_usage_day_evidence(self.month_row(), 20)
		self.assertEqual(found["line"]["value"], 10 * 1_000_000_000)
		self.assertEqual(found["derivation"], {"kind": "Evidence", "evidence": evidence(10)})

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
		self.assertEqual(
			(found["report"], found["derivation"]), (None, {"kind": "Segment", "segment": "segment-1"})
		)


class TestDerivationCheck(BillingTestCase):
	def setUp(self):
		ensure_team(test_usage_month.TEAM)

	def write(self, service: str, subject: str, day: datetime.date, **values) -> None:
		row = {**test_usage_month.line(1, 5, **values), "service": service, "subject": subject, "day": day}
		usage_month.write_lines([row], "report-1", "Pushed")

	def violations(self) -> dict:
		found = check_days_carry_a_derivation("2026-07-10")
		return {violation.subject: violation for violation in found if violation.subject in SERVICES}

	def test_days_without_a_derivation_are_listed_once_per_service(self):
		storage, ai = SERVICES
		for day in (1, 2):
			self.write(storage, "bucket-a", datetime.date(2026, 6, day))
		self.write(storage, "bucket-b", datetime.date(2026, 7, 3))
		self.write(storage, "bucket-c", datetime.date(2026, 7, 4), evidence={"v": 1})
		self.write(ai, "team-a", datetime.date(2026, 7, 5))
		found = self.violations()
		self.assertEqual(sorted(found), sorted(SERVICES))
		self.assertEqual((found[storage].check, found[storage].actual, found[ai].actual), ("M8", 3, 1))
		self.assertIn("2 subject(s)", found[storage].detail)
		self.assertIn("bucket-a, bucket-b", found[storage].detail)

	def test_months_before_last_month_and_pruned_months_are_not_listed(self):
		storage, ai = SERVICES
		self.write(storage, "bucket-a", datetime.date(2026, 5, 31))
		self.write(ai, "team-a", datetime.date(2026, 7, 5))
		frappe.db.set_value("Usage Month", {"service": ai}, "pruned", 1)
		self.assertEqual(self.violations(), {})

	def test_days_stored_before_evidence_was_sent_are_not_listed(self):
		self.write(SERVICES[0], "bucket-a", datetime.date(2026, 7, 3))
		count_underived_days_from_now.execute()
		self.assertEqual(self.violations(), {})
		self.write(SERVICES[0], "bucket-a", datetime.date(2026, 7, 4))
		self.assertEqual(self.violations()[SERVICES[0]].actual, 1)
