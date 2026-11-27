# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Usage evidence is kept 13 months, and readiness says when a billed day cannot be traced to it."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.platform import readiness
from central.billing.revenue import usage_month, usage_reports, usage_retention
from central.billing.revenue.usage_month import bit
from central.billing.tests.utils import BillingTestCase, ensure_team
from central.services.doctype.service.service import STORAGE_SERVICE, ensure_services

TEAM = "team-usage-retention"
SUBJECT = "usage-retention-bucket"
SUBSCRIPTION = "usage-retention-subscription"
TODAY = datetime.date(2026, 11, 26)
OLD = datetime.date(2025, 8, 1)  # before the cutoff, 1 October 2025


def line(day: datetime.date, quantity: float = 30) -> dict:
	return {
		"service": STORAGE_SERVICE,
		"meter": "bytes_stored",
		"subject": SUBJECT,
		"dimension": "",
		"day": day,
		"aggregation": "Level",
		"team": TEAM,
		"subscription": SUBSCRIPTION,
		"resource_type": "Storage",
		"unit": "GB",
		"quantity": quantity,
		"as_of": datetime.datetime.combine(day, datetime.time(12)),
	}


def checks(code: str) -> list:
	return [violation for violation in readiness.CHECKS[code][1]() if violation.team in (TEAM, None)]


class TestUsageRetention(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_services()

	def write(self, day: datetime.date, report: str | None = None, billed: bool = True) -> str:
		"""Write a day under its own report and return its month row, billed by an invoice unless told not to."""
		if report is None:
			report = usage_reports.record_lines(STORAGE_SERVICE, usage_reports.READ_BY_CENTRAL, [line(day)])
		usage_month.write_lines([line(day)], report or None, "Read By Central")
		name = frappe.db.get_value(usage_month.DOCTYPE, {"subject": SUBJECT, "month": day.replace(day=1)})
		if billed:
			usage_month.stamp_days({name: bit(day.day)}, "INV-TEST")
		return name

	def test_an_old_billed_month_keeps_its_totals_and_drops_its_days(self):
		name = self.write(OLD.replace(day=14))
		frappe.db.set_value(usage_month.DOCTYPE, name, {"quantity": 0.97, "locked_rate": 2.5})

		usage_retention.prune_old_months(TODAY)

		month = frappe.db.get_value(
			usage_month.DOCTYPE,
			name,
			["pruned", "slots", "d14", "quantity", "locked_rate", "billed"],
			as_dict=True,
		)
		self.assertEqual(
			(month.pruned, month.slots, month.d14, month.quantity, month.locked_rate, month.billed),
			(1, None, 0, 0.97, 2.5, bit(14)),
		)
		self.assertEqual(usage_month.day_rows({"subject": SUBJECT}), [])

	def test_a_line_for_a_month_past_retention_is_ignored(self):
		name = self.write(OLD.replace(day=14))
		usage_retention.prune_old_months(TODAY)

		written = usage_month.write_lines(
			[line(OLD.replace(day=14), 50), line(OLD.replace(day=15), 50)], "report-late", "Read By Central"
		)

		self.assertEqual((written.count, written.corrections, written.conflicts), (0, 0, []))
		month = frappe.get_doc(usage_month.DOCTYPE, name)
		self.assertEqual((month.filled, month.d15, month.slots, month.corrections), (bit(14), 0, None, []))

	def test_a_month_with_something_left_to_bill_is_kept(self):
		self.write(OLD.replace(day=14), billed=False)
		self.write(TODAY.replace(day=1))
		with_correction = self.write(OLD.replace(month=9, day=3))
		usage_month.write_lines([line(OLD.replace(month=9, day=3), 60)], None, "Read By Central")
		self.assertEqual(frappe.get_doc(usage_month.DOCTYPE, with_correction).corrections[0].status, "Open")

		usage_retention.prune_old_months(TODAY)

		pruned = frappe.get_all(usage_month.DOCTYPE, filters={"subject": SUBJECT, "pruned": 1}, pluck="name")
		self.assertEqual(pruned, [])

	def test_an_old_report_is_deleted_with_its_body(self):
		old = usage_reports.record_lines(STORAGE_SERVICE, usage_reports.READ_BY_CENTRAL, [line(OLD)])
		recent = usage_reports.record_lines(STORAGE_SERVICE, usage_reports.READ_BY_CENTRAL, [line(TODAY)])
		frappe.db.set_value(usage_reports.DOCTYPE, old, "received_at", datetime.datetime(2025, 9, 30, 23))

		usage_retention.prune_reports(TODAY)

		self.assertFalse(frappe.db.exists(usage_reports.DOCTYPE, old))
		self.assertFalse(frappe.db.exists("File", {"attached_to_name": old}))
		self.assertTrue(usage_reports.is_intact(recent))

	def test_a_billed_day_without_a_report_is_a_readiness_row(self):
		today = frappe.utils.getdate()
		name = self.write(today.replace(day=1), report="")
		self.write(today.replace(day=2))

		[violation] = [v for v in checks("M5") if v.subject == name]
		self.assertEqual(violation.actual, 1)

	def test_a_damaged_body_found_by_the_sample_is_a_readiness_row(self):
		intact = usage_reports.record_lines(STORAGE_SERVICE, usage_reports.READ_BY_CENTRAL, [line(TODAY)])
		damaged = usage_reports.record_lines(STORAGE_SERVICE, usage_reports.READ_BY_CENTRAL, [line(TODAY, 9)])
		frappe.db.set_value(usage_reports.DOCTYPE, damaged, "body_sha256", "0" * 64)

		with patch.object(usage_retention, "SAMPLE_SIZE", 100_000):
			usage_retention.sample_report_bodies()

		flagged = {violation.subject for violation in checks("M6")}
		self.assertIn(damaged, flagged)
		self.assertNotIn(intact, flagged)
