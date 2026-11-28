# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A Usage Segment is only added and closed once, and a subject has one open segment per meter."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.revenue import usage_segments
from central.billing.tests.utils import BillingTestCase, ensure_team
from central.services.doctype.service.service import NETWORK_SERVICE, ensure_services

TEAM = "team-usage-segments"
SUBJECT = "usage-segments-subject"
# The ledger is generic, so a meter that bills nothing is enough to test the record.
METER = "test_seats"


def at(day: str) -> datetime.datetime:
	return frappe.utils.get_datetime(day)


class TestUsageSegmentRecord(BillingTestCase):
	def setUp(self):
		ensure_services()
		ensure_team(TEAM)
		self.segment = self.insert(at("2026-06-01"))

	def test_a_subject_has_one_open_segment(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert(at("2026-06-03"))

		# The unique key holds even for a writer that skips the check.
		duplicate = frappe.get_doc({**self.values(at("2026-06-03")), "doctype": "Usage Segment"})
		duplicate.flags.ignore_validate = True
		with self.assertRaises(frappe.UniqueValidationError):
			duplicate.insert(ignore_permissions=True)

	def test_a_segment_cannot_start_before_the_last_one_ended(self):
		usage_segments.close_segment(self.segment.name, at("2026-06-05"), usage_segments.OPERATOR)

		with self.assertRaises(frappe.ValidationError):
			self.insert(at("2026-06-04"))
		self.assertEqual(self.insert(at("2026-06-05")).open_key, self.segment.open_key)

	def test_a_segment_is_closed_once_and_clears_its_key(self):
		usage_segments.close_segment(
			self.segment.name, at("2026-06-04"), usage_segments.OPERATOR, "wrong host"
		)

		closed = frappe.get_doc("Usage Segment", self.segment.name)
		self.assertEqual(closed.ends_at, at("2026-06-04"))
		self.assertEqual(closed.closed_reference, "wrong host")
		self.assertIsNone(closed.open_key)
		with self.assertRaises(frappe.PermissionError):
			usage_segments.close_segment(self.segment.name, at("2026-06-05"), usage_segments.OPERATOR)

	def test_any_other_edit_is_refused(self):
		self.segment.quantity = 2
		with self.assertRaises(frappe.PermissionError):
			self.segment.save(ignore_permissions=True)

	def test_a_segment_is_never_deleted(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Usage Segment", self.segment.name, ignore_permissions=True)

	def test_a_segment_cannot_end_before_it_starts(self):
		with self.assertRaises(frappe.ValidationError):
			usage_segments.close_segment(self.segment.name, at("2026-05-31"), usage_segments.OPERATOR)

	def test_a_subject_doctype_with_no_provider_bills_nothing_and_logs_once(self):
		before = frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from")
		self.addCleanup(frappe.db.set_value, "Service", NETWORK_SERVICE, "bill_from", before)
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", "2026-01-01")

		with patch.object(usage_segments, "_unregistered", set()), patch("frappe.logger") as logger:
			self.assertEqual(usage_segments.project([SUBJECT], "2026-06-01", "2026-06-30"), 0)
			self.assertEqual(usage_segments.project([SUBJECT], "2026-06-01", "2026-06-30"), 0)

		logger.return_value.warning.assert_called_once()

	def insert(self, starts_at):
		return usage_segments.insert_segment(**self.values(starts_at))

	def values(self, starts_at) -> dict:
		return {
			"service": NETWORK_SERVICE,
			"meter": METER,
			"subject": SUBJECT,
			# No billing_segment_subjects provider knows this doctype.
			"subject_doctype": "ToDo",
			"team": TEAM,
			"quantity": 1,
			"starts_at": starts_at,
			"opened_source": usage_segments.OPERATOR,
		}


class TestCorrectionEvidence(BillingTestCase):
	"""A correction names what set the billed value and what corrected it."""

	def test_each_side_names_its_own_evidence(self):
		from central.billing.revenue.usage_corrections import get_evidence

		cases = [
			({"original_report": "r1", "report": "r2"}, "report r1 → r2"),
			({"original_segment": "s1", "segment": "s2"}, "segment s1 → s2"),
			({"original_report": "r1", "segment": "s2"}, "report r1 → segment s2"),
			({"original_segment": "s1", "report": "r2"}, "segment s1 → report r2"),
		]
		for fields, expected in cases:
			self.assertEqual(get_evidence(frappe._dict(fields)), expected)
