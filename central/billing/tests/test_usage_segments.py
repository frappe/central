# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A Usage Segment is only added and closed once, and a subject has one open segment per meter."""

import frappe

from central.billing.revenue import usage_segments
from central.billing.tests.test_ipv4_days import IPv4DaysTestCase, at
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER


class TestUsageSegmentRecord(IPv4DaysTestCase):
	team = "team-usage-segments"
	server = "usage-segments-vm"

	def setUp(self):
		super().setUp()
		self.hold(at("2026-06-01"))
		self.segment = frappe.get_doc("Usage Segment", {"subject": self.server})

	def test_a_subject_has_one_open_segment(self):
		with self.assertRaises(frappe.ValidationError):
			self.insert(at("2026-06-03"))

		# The unique key holds even for a writer that skips the check.
		duplicate = frappe.get_doc({**self.values(at("2026-06-03")), "doctype": "Usage Segment"})
		duplicate.flags.ignore_validate = True
		with self.assertRaises(frappe.UniqueValidationError):
			duplicate.insert(ignore_permissions=True)

	def test_a_segment_cannot_start_before_the_last_one_ended(self):
		self.hold(at("2026-06-05"), quantity=0)

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

	def insert(self, starts_at):
		return usage_segments.insert_segment(**self.values(starts_at))

	def values(self, starts_at) -> dict:
		return {
			"service": NETWORK_SERVICE,
			"meter": PUBLIC_IPV4_METER,
			"subject": self.server,
			"team": self.team,
			"quantity": 1,
			"starts_at": starts_at,
			"opened_source": usage_segments.OPERATOR,
		}
