# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A month row keeps one value per UTC day, names the report behind each, and never changes a billed day."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.revenue import usage_month, usage_month_days
from central.billing.revenue.usage_month import OPEN, bit
from central.billing.tests.test_credits import run_workers
from central.billing.tests.utils import BillingTestCase, ensure_team

TEAM = "team-usage-month"
SUBJECT = "usage-month-bucket"
SUBSCRIPTION = "usage-month-subscription"
SERVICE = "storage"


def line(day: int, quantity: float, aggregation: str = "Level", **values) -> dict:
	return {
		"service": SERVICE,
		"meter": "bytes_stored",
		"subject": SUBJECT,
		"dimension": "",
		"day": datetime.date(2026, 6, day),
		"aggregation": aggregation,
		"team": TEAM,
		"subscription": SUBSCRIPTION,
		"resource_type": "Storage",
		"unit": "GB",
		"quantity": quantity,
		"as_of": datetime.datetime(2026, 6, day, 12, 0),
		**values,
	}


def on_own_connection(fn) -> None:
	"""Run `fn` and commit it on a second database connection, as another worker would."""
	[outcome] = run_workers(1, lambda _i: fn()).values()
	if outcome != "ok":
		raise AssertionError(f"the other worker failed: {outcome}")


class TestUsageMonth(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)

	def write(self, *lines, report: str = "report-1", source: str = "Read By Central"):
		return usage_month.write_lines(list(lines), report, source)

	def days(self):
		return usage_month_days.day_rows({"team": TEAM})

	def month(self, subscription: str = SUBSCRIPTION):
		return frappe.get_doc(usage_month.DOCTYPE, {"subject": SUBJECT, "subscription": subscription})

	def open_days(self) -> list[int]:
		[month] = usage_month.locked_meter_months(SUBSCRIPTION, "Storage", "", datetime.date(2026, 6, 1))
		return [day.number for day in month.get_open_days()]

	def bill(self, *days: int) -> None:
		"""Mark days billed by an invoice."""
		usage_month.stamp_days({self.month().name: sum(bit(day) for day in days)}, "invoice-1")

	def test_a_line_fills_its_day_and_names_its_report(self):
		self.assertEqual(self.write(line(14, 30)).count, 1)
		[day] = self.days()
		self.assertEqual(
			(day.day, day.quantity, day.report, day.source),
			(datetime.date(2026, 6, 14), 30, "report-1", "Read By Central"),
		)
		self.assertEqual(self.open_days(), [14])

	def test_one_row_holds_every_day_of_the_month(self):
		self.write(line(1, 10), line(2, 20))
		self.write(line(30, 30))
		self.assertEqual(frappe.db.count(usage_month.DOCTYPE, {"subject": SUBJECT}), 1)
		self.assertEqual([d.quantity for d in self.days()], [10, 20, 30])

	def test_a_level_day_keeps_its_peak(self):
		for quantity in (10, 50, 20):
			self.write(line(1, quantity))
		self.assertEqual([d.quantity for d in self.days()], [50])

	def test_a_sum_day_takes_the_newest_total(self):
		self.write(line(1, 10, "Sum", as_of=datetime.datetime(2026, 6, 1, 12)))
		self.write(line(1, 4, "Sum", as_of=datetime.datetime(2026, 6, 1, 18)))
		self.write(line(1, 9, "Sum", as_of=datetime.datetime(2026, 6, 1, 15)))
		self.assertEqual([d.quantity for d in self.days()], [4])

	def test_an_estimate_fills_only_an_empty_day_and_a_reading_replaces_it(self):
		self.write(line(1, 30))
		self.write(
			line(1, 99, estimated=1, as_of=None), line(2, 30, estimated=1, as_of=None), source="Estimated"
		)
		self.assertEqual(
			[(d.quantity, d.estimated, d.source) for d in self.days()],
			[(30, 0, "Read By Central"), (30, 1, "Estimated")],
		)
		self.write(line(2, 10), report="report-2")
		self.assertEqual([(d.quantity, d.estimated, d.report) for d in self.days()][1], (10, 0, "report-2"))

	def test_a_written_off_day_is_kept_but_never_open(self):
		self.write(line(1, 30, written_off=1), line(2, 30))
		self.assertEqual([(d.day.day, d.written_off) for d in self.days()], [(1, 1), (2, 0)])
		self.assertEqual(self.open_days(), [2])

	def test_a_billed_day_keeps_its_value_and_a_higher_one_is_an_open_correction(self):
		self.write(line(14, 30))
		self.bill(14)
		written = self.write(line(14, 40), report="report-2")
		self.assertEqual((written.count, written.corrections), (0, 1))
		self.assertEqual([(d.quantity, d.invoice) for d in self.days()], [(30, "invoice-1")])
		self.assertEqual(self.open_days(), [])
		[correction] = self.month().corrections
		self.assertEqual(
			(correction.day, correction.billed_value, correction.value, correction.status),
			(14, 30, 40, OPEN),
		)
		self.assertEqual((correction.original_report, correction.report), ("report-1", "report-2"))

	def test_a_lower_value_of_a_billed_sum_day_is_an_open_correction(self):
		self.write(line(14, 30, "Sum"))
		self.bill(14)
		self.write(line(14, 20, "Sum", as_of=datetime.datetime(2026, 6, 15)))
		# The next draft decides whether it lowers the bill.
		self.assertEqual([c.status for c in self.month().corrections], [OPEN])

	def test_a_billed_day_keeps_one_pending_correction_and_a_resend_adds_none(self):
		self.write(line(14, 30))
		self.bill(14)
		self.write(line(14, 40))
		self.write(line(14, 40))
		self.write(line(14, 45))
		self.assertEqual([(c.value, c.status) for c in self.month().corrections], [(45, OPEN)])

	def test_a_reused_subject_bills_each_day_on_the_subscription_that_held_it_first(self):
		self.write(line(1, 10))
		self.write(
			line(1, 20, subscription="later-subscription"), line(2, 20, subscription="later-subscription")
		)
		self.assertEqual(
			[(d.day.day, d.quantity, d.subscription) for d in self.days()],
			[(1, 20, SUBSCRIPTION), (2, 20, "later-subscription")],
		)

	def test_subjects_with_a_value_for_a_day_are_found_by_its_bit(self):
		self.write(line(14, 30))
		self.assertIn(SUBJECT, usage_month_days.subjects_with_day(SERVICE, "2026-06-14"))
		self.assertNotIn(SUBJECT, usage_month_days.subjects_with_day(SERVICE, "2026-06-15"))

	def write_after_another_worker(self, quantity: float):
		"""Write day 1 in a transaction that began before another worker committed the month row."""
		frappe.get_all(usage_month.DOCTYPE, limit=1)  # Opens this transaction's snapshot first.
		on_own_connection(lambda: usage_month.write_lines([line(1, 10)], "report-1", "Read By Central"))
		self.addCleanup(
			on_own_connection,
			lambda: frappe.db.delete(usage_month.DOCTYPE, {"subject": SUBJECT}),
		)
		# Ends this transaction first, so the cleanup is not waiting on its row lock.
		self.addCleanup(frappe.db.rollback)
		return self.write(line(1, quantity))

	def test_a_month_another_worker_committed_meanwhile_is_written_once(self):
		written = self.write_after_another_worker(40)
		if written.conflicts:
			# With snapshot isolation (MariaDB 11.8 default) the lock is refused and the whole
			# batch comes back to be sent again; without it the row is written under the lock.
			self.assertEqual((written.count, len(written.conflicts)), (0, 1))
			frappe.db.rollback()
			written = self.write(line(1, 40))
		self.assertEqual((written.count, written.conflicts), (1, []))
		self.assertEqual([d.quantity for d in self.days()], [40])

	def test_a_batch_whose_lock_is_refused_is_sent_again_whole(self):
		self.write(line(1, 10))
		# Under snapshot isolation, a row another worker changed after this transaction began
		# refuses the lock.
		with patch.object(usage_month, "_locked_months", side_effect=frappe.QueryDeadlockError):
			written = self.write(line(1, 40), line(2, 40))
		self.assertEqual((written.count, len(written.conflicts)), (0, 2))
		self.assertEqual([d.quantity for d in self.days()], [10])
