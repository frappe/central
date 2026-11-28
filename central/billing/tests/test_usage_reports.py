# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Each accepted report is kept with its raw body, so a billed value can be traced and verified."""

import json

import frappe

from central.billing.revenue import service_reports, usage_reports
from central.billing.tests.test_service_reports import SECRET, ServiceReportsCase, line, signed

AS_OF = "2026-06-20T06:30:00Z"


class TestUsageReports(ServiceReportsCase):
	def reports(self):
		return frappe.get_all(
			usage_reports.DOCTYPE,
			filters={"service": "storage"},
			fields=["name", "kind", "line_count", "accepted_count", "rejected_count", "signature"],
		)

	def test_a_signed_report_keeps_its_body_signature_and_counts(self):
		before = {report.name for report in self.reports()}
		lines = [line("2026-06-19", 10), line("2026-06-20", 12, subject="not-a-bucket")]
		raw, signature = signed({"as_of": AS_OF, "lines": lines})
		service_reports.accept_report("storage", signature, raw)
		[report] = [report for report in self.reports() if report.name not in before]
		self.assertEqual(
			(report.kind, report.line_count, report.accepted_count, report.rejected_count),
			(usage_reports.PUSHED, 2, 1, 1),
		)
		self.assertEqual(usage_reports.get_body(report.name), raw)
		self.assertTrue(usage_reports.is_intact(report.name))
		self.assertTrue(usage_reports.has_valid_signature(report.name))

	def test_a_report_with_a_wrong_signature_is_not_kept(self):
		before = len(self.reports())
		with self.assertRaises(frappe.PermissionError):
			self.send([line("2026-06-20", 10)], secret="not-the-secret")
		self.assertEqual(len(self.reports()), before)

	def test_a_changed_body_is_no_longer_intact(self):
		name = self.sent_report()
		frappe.db.set_value(usage_reports.DOCTYPE, name, "body_sha256", "0" * 64, update_modified=False)
		self.assertFalse(usage_reports.is_intact(name))

	def test_a_rotated_secret_cannot_verify_an_older_body(self):
		name = self.sent_report()
		storage = frappe.get_doc("Service", "storage")
		storage.report_secret = f"{SECRET}-rotated"
		storage.save()
		self.assertFalse(usage_reports.has_valid_signature(name))

	def test_centrals_own_lines_hash_the_same_in_any_key_order(self):
		first = usage_reports.central_body([{"subject": "a", "value": 1, "day": "2026-06-01"}])
		second = usage_reports.central_body([{"day": "2026-06-01", "value": 1, "subject": "a"}])
		self.assertEqual(first, second)

	def test_centrals_own_report_keeps_its_lines_and_no_signature(self):
		lines = [{"subject": "a", "day": "2026-06-01", "value": 1.5}]
		name = usage_reports.record_lines("storage", usage_reports.READ_BY_CENTRAL, lines)
		self.assertEqual(json.loads(usage_reports.get_body(name)), {"lines": lines})
		self.assertTrue(usage_reports.is_intact(name))
		self.assertFalse(usage_reports.has_valid_signature(name))

	def sent_report(self) -> str:
		before = {report.name for report in self.reports()}
		self.send([line("2026-06-20", 10)])
		[name] = [report.name for report in self.reports() if report.name not in before]
		return name
