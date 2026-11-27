# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A public IPv4 bills on its server for each UTC day it was held while the server was billed."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.api.dashboard._shared import _describe_line
from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates
from central.billing.platform import readiness
from central.billing.revenue import usage_recount, usage_segments
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, make_plan, seed_running_resource, usage_days
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER

CLUSTER = "ap-south-1"
VM_PLAN = "ipv4-days-vm-plan"
ADDRESS = "203.0.113.20"
JUNE = [f"2026-06-{day:02d}" for day in range(1, 31)]
BEFORE_JUNE = datetime.date(2026, 1, 1)


def at(day: str, hours: float = 0) -> datetime.datetime:
	"""A moment of a UTC day, in system time."""
	return frappe.utils.add_to_date(utc_day_start(day), hours=hours)


class IPv4DaysTestCase(IntegrationTestCase):
	"""A running server, billed all of June, that holds one public IPv4."""

	team = "team-ipv4-days"
	server = "ipv4-days-vm"
	currency = "INR"

	def setUp(self):
		frappe.db.delete("Virtual Machine", {"team": self.team})
		self.addCleanup(frappe.db.delete, "Virtual Machine", {"team": self.team})
		self.set_service(bill_from=BEFORE_JUNE)
		self.set_meter_aggregation(usage_segments.STATE)
		make_plan(VM_PLAN)
		self.subscription = seed_running_resource(
			self.team, self.server, CLUSTER, VM_PLAN, rate=1000, currency=self.currency
		)
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", ADDRESS)

	def set_service(self, **values) -> None:
		before = frappe.db.get_value("Service", NETWORK_SERVICE, list(values), as_dict=True)
		self.addCleanup(frappe.db.set_value, "Service", NETWORK_SERVICE, before)
		frappe.db.set_value("Service", NETWORK_SERVICE, values)

	def set_meter_aggregation(self, aggregation: str) -> None:
		meter = {"parent": NETWORK_SERVICE, "meter_key": PUBLIC_IPV4_METER}
		before = frappe.db.get_value("Service Meter", meter, "aggregation")
		self.addCleanup(frappe.db.set_value, "Service Meter", meter, "aggregation", before)
		frappe.db.set_value("Service Meter", meter, "aggregation", aggregation)

	def hold(self, moment, quantity: int = 1) -> None:
		"""Record the addresses the server holds from `moment`, as a state report does."""
		server = frappe.get_doc("Virtual Machine", self.server)
		usage_segments.set_quantity(
			NETWORK_SERVICE, PUBLIC_IPV4_METER, server, quantity, moment, usage_segments.STATE_REPORT
		)

	def hold_days(self, first: str, last: str) -> None:
		self.hold(at(first))
		self.hold(at(last, hours=24), quantity=0)

	def days(self, since: str = JUNE[0], until: str = JUNE[-1]) -> list[str]:
		usage_segments.project([self.server], since, until)
		return [str(day.day) for day in usage_days(service=NETWORK_SERVICE, subject=self.server)]

	def segments(self) -> list:
		return frappe.get_all(
			"Usage Segment",
			filters={"subject": self.server},
			fields=["quantity", "starts_at", "ends_at", "opened_source", "closed_source"],
			order_by="starts_at asc",
		)

	def observe(self, observed_at, **state) -> None:
		server = frappe.get_doc("Virtual Machine", self.server)
		server.record_observed_state(state, observed_at)

	def invoice(self, start: str = "2026-06-01", end: str = "2026-06-30"):
		return frappe.get_doc("Invoice", generate_team_invoice(self.team, start, end))

	def ip_line(self, start: str = "2026-06-01", end: str = "2026-06-30"):
		[line] = [li for li in self.invoice(start, end).items if li.resource_type == "IP"]
		return line

	def readiness_details(self) -> list[str]:
		return [v.detail for v in readiness.check_public_ipv4_is_billed() if v.subject == self.server]


class TestIPv4DayBilling(IPv4DaysTestCase):
	def test_ten_days_of_thirty_bill_a_third_of_an_address_month(self):
		self.hold_days(JUNE[0], JUNE[9])

		line = self.ip_line()
		self.assertAlmostEqual(line.quantity, 10 / 30)
		self.assertEqual(line.amount, frappe.utils.flt(170 * 10 / 30, 2))

	def test_the_line_names_the_plan_and_the_server(self):
		frappe.db.set_value("Virtual Machine", self.server, "title", "Web box")
		self.hold_days(JUNE[0], JUNE[2])

		row = _describe_line(self.team, self.ip_line(), ("2026-06-01", "2026-06-30"))
		self.assertEqual(row["item"], "Public IPv4 · Web box")
		self.assertTrue(row["detail"].startswith("Metered · "))

	def test_an_address_held_for_part_of_a_day_bills_the_day(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)

		self.observe(at("2026-06-07", hours=10), public_ipv4=ADDRESS)
		self.observe(at("2026-06-07", hours=11), public_ipv4=None)

		self.assertEqual(self.days(), ["2026-06-07"])
		self.assertAlmostEqual(self.ip_line().quantity, 1 / 30)

	def test_a_stopped_server_still_bills_its_address(self):
		self.hold(at("2026-06-01"))

		self.observe(at("2026-06-03", hours=5), status="Stopped")

		self.assertEqual(self.days(), JUNE)

	def test_a_day_with_billing_paused_throughout_bills_nothing(self):
		self.hold_days(JUNE[8], JUNE[11])
		# 00:00 IST on the 10th is 18:30 UTC on the 9th; billing resumes at 06:30 UTC on the 12th.
		add_segment(self.subscription, "Paused", None, "2026-06-10 00:00:00")
		add_segment(self.subscription, "Resumed", 1000, "2026-06-12 12:00:00", plan=VM_PLAN)

		self.assertEqual(self.days(), ["2026-06-09", "2026-06-12"])

	def test_a_day_bills_only_when_held_at_a_moment_the_server_was_billed(self):
		add_segment(self.subscription, "Paused", None, at("2026-06-10", hours=6))
		self.hold(at("2026-06-10", hours=20))

		self.assertEqual(self.days(), [])

		add_segment(self.subscription, "Resumed", 1000, at("2026-06-12", hours=1), plan=VM_PLAN)
		self.assertEqual(self.days(), JUNE[11:])

	def test_a_server_with_no_open_segment_is_free_until_billing_starts(self):
		frappe.db.delete("Subscription Change", {"subscription": self.subscription})
		self.hold(at("2026-06-01"))

		self.assertEqual(self.days(), [])

		# A trial converts: the server's billing starts mid-day on the 15th.
		add_segment(self.subscription, "Created", 1000, at("2026-06-15", hours=12), plan=VM_PLAN)
		self.assertEqual(self.days(), JUNE[14:])

	def test_the_termination_day_bills_once(self):
		self.hold(at("2026-06-01"))
		add_segment(self.subscription, "Cancelled", None, at("2026-06-20", hours=10))

		frappe.get_doc("Virtual Machine", self.server).record_terminated(at("2026-06-20", hours=10))

		self.assertEqual(self.days(), JUNE[:20])
		self.assertEqual(self.segments()[0].closed_source, usage_segments.TERMINATION)


class TestIPv4Segments(IPv4DaysTestCase):
	"""A segment is written when the addresses change, and never for a report that changes nothing."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)

	def test_attach_release_and_terminate_each_write_one_row(self):
		self.observe(at("2026-06-02"), public_ipv4=ADDRESS)
		self.assertEqual(len(self.segments()), 1)

		self.observe(at("2026-06-05"), public_ipv4=None)
		self.observe(at("2026-06-07"), public_ipv4=ADDRESS)
		frappe.get_doc("Virtual Machine", self.server).record_terminated(at("2026-06-09"))

		self.assertEqual(
			[(row.starts_at, row.ends_at) for row in self.segments()],
			[(at("2026-06-02"), at("2026-06-05")), (at("2026-06-07"), at("2026-06-09"))],
		)

	def test_a_report_pause_resume_or_conversion_writes_no_row(self):
		self.observe(at("2026-06-02"), public_ipv4=ADDRESS)

		self.observe(at("2026-06-03"), public_ipv4=ADDRESS, status="Stopped")
		self.observe(at("2026-06-04"), status="Running")
		add_segment(self.subscription, "Paused", None, at("2026-06-05"))
		add_segment(self.subscription, "Resumed", 1000, at("2026-06-06"), plan=VM_PLAN)
		add_segment(self.subscription, "Plan Changed", 1000, at("2026-06-07"), plan=VM_PLAN)

		self.assertEqual(len(self.segments()), 1)

	def test_a_late_report_never_starts_before_the_last_change(self):
		self.observe(at("2026-06-05"), public_ipv4=ADDRESS)

		self.hold(at("2026-06-03"), quantity=0)

		[segment] = self.segments()
		self.assertEqual((segment.starts_at, segment.ends_at), (at("2026-06-05"), at("2026-06-05")))

	def test_a_save_without_a_region_report_starts_now(self):
		frappe.db.set_value("Virtual Machine", self.server, "state_observed_at", at("2026-06-01"))
		server = frappe.get_doc("Virtual Machine", self.server)
		server.public_ipv4 = ADDRESS

		server.save_as_system()

		[segment] = frappe.get_all("Usage Segment", {"subject": self.server}, ["starts_at", "opened_source"])
		self.assertEqual(segment.opened_source, usage_segments.OPERATOR)
		self.assertGreater(segment.starts_at, at(str(utc_today())))

	def test_no_segment_is_written_while_the_meter_keeps_day_values(self):
		self.set_meter_aggregation("Level")

		self.observe(at("2026-06-02"), public_ipv4=ADDRESS)

		self.assertEqual(self.segments(), [])

	def test_the_hourly_run_writes_no_row_and_only_days_not_yet_written(self):
		self.assertFalse(
			[hook for hook in frappe.get_hooks("scheduler_events")["hourly"] if "ipv4" in hook.lower()]
		)
		self.observe(at(str(utc_today())), public_ipv4=ADDRESS)
		since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)

		self.assertEqual(usage_segments.project_changed(since), 1)
		self.assertEqual(usage_segments.project_changed(frappe.utils.now_datetime()), 0)
		self.assertEqual(len(self.segments()), 1)
		self.assertEqual(self.days(str(utc_today()), str(utc_today())), [str(utc_today())])


class TestIPv4LateReports(IPv4DaysTestCase):
	def test_a_late_change_inside_an_invoiced_month_is_kept_as_a_correction(self):
		self.hold(at("2026-06-01"))
		self.invoice()

		self.hold(at("2026-06-20"), quantity=2)
		self.days()

		corrections = frappe.get_all(
			"Usage Month Correction",
			filters={"parent": ["in", self.month_rows()]},
			fields=["day", "billed_value", "value", "status"],
			order_by="day asc",
		)
		self.assertEqual([row.day for row in corrections], list(range(20, 31)))
		self.assertEqual({(row.billed_value, row.value, row.status) for row in corrections}, {(1, 2, "Open")})

	def test_a_late_day_of_a_drafted_month_bills_in_the_next_one(self):
		self.hold_days(JUNE[0], JUNE[19])
		self.invoice()

		self.hold(at("2026-06-25"))

		line = self.ip_line("2026-07-01", "2026-07-31")
		self.assertAlmostEqual(line.quantity, 1 + 6 / 30)

	def test_the_draft_writes_the_days_itself(self):
		self.hold_days(JUNE[0], JUNE[4])
		self.assertEqual(usage_days(service=NETWORK_SERVICE, subject=self.server), [])

		counted = usage_recount.recount_team(self.team, "2026-06-30")

		self.assertTrue(counted.months)
		self.assertEqual(len(usage_days(service=NETWORK_SERVICE, subject=self.server)), 5)

	def month_rows(self) -> list[str]:
		return frappe.get_all("Usage Month", filters={"subject": self.server}, pluck="name")


class TestIPv4DayBillingInUSD(IPv4DaysTestCase):
	team = "team-ipv4-days-usd"
	server = "ipv4-days-usd-vm"
	currency = "USD"

	def test_an_address_held_all_month_bills_one_address_month(self):
		self.hold(at("2026-06-01"))

		line = self.ip_line()
		self.assertAlmostEqual(line.quantity, 1)
		self.assertEqual(line.amount, 2)


class TestUnpricedIPv4(IPv4DaysTestCase):
	def setUp(self):
		super().setUp()
		plan = frappe.db.get_value("Plan Includes", {"resource_type": "IP", "parenttype": "Plan"}, "parent")
		self.ip_plan = plan
		rates = get_catalog_rates("Plan", plan)
		self.addCleanup(set_catalog_rates, "Plan", plan, [dict(row) for row in rates])
		set_catalog_rates("Plan", plan, [dict(row) for row in rates if row.currency != "INR"])

	def test_a_day_with_no_price_is_written_and_holds_the_draft(self):
		self.hold_days(JUNE[0], JUNE[9])
		self.assertEqual(len(self.days()), 10)

		with self.assertRaises(frappe.ValidationError):
			generate_team_invoice(self.team, "2026-06-01", "2026-06-30")
		self.assertFalse(frappe.db.exists("Invoice", {"team": self.team}))

		set_catalog_rates("Plan", self.ip_plan, [{"currency": "INR", "rate": 170}])
		self.assertAlmostEqual(self.ip_line().quantity, 10 / 30)

	def test_readiness_lists_the_unpriced_server(self):
		self.hold(at(str(utc_today() - datetime.timedelta(days=1))))

		details = self.readiness_details()

		self.assertEqual(len(details), 1)
		self.assertIn("no price in INR", details[0])

	def test_readiness_skips_an_unpriced_server_with_no_address(self):
		self.hold(at("2026-06-01"))
		self.hold(at("2026-06-02"), quantity=0)

		self.assertEqual(self.readiness_details(), [])


class TestIPv4Readiness(IPv4DaysTestCase):
	def test_readiness_skips_a_priced_server_that_holds_an_address(self):
		self.hold(at("2026-06-01"))

		self.assertEqual(self.readiness_details(), [])


class TestIPv4Install(IPv4DaysTestCase):
	"""A fresh install bills public IPv4 from its install day."""

	def test_a_fresh_install_bills_from_its_install_day(self):
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
		with patch.object(usage_segments, "utc_today", return_value=datetime.date(2026, 6, 20)):
			usage_segments.start_on_install()

		self.assertEqual(
			frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"), datetime.date(2026, 6, 20)
		)

	def test_a_fresh_install_runs_the_start_hook(self):
		self.assertIn(
			"central.billing.revenue.usage_segments.start_on_install", frappe.get_hooks("after_install")
		)

	def test_install_keeps_a_cutover_day_already_set(self):
		with patch.object(usage_segments, "utc_today", return_value=datetime.date(2026, 6, 20)):
			usage_segments.start_on_install()

		self.assertEqual(frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"), BEFORE_JUNE)

	def test_no_day_is_written_before_the_cutover_day_is_set(self):
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
		self.hold(at("2026-06-01"))

		self.assertEqual(self.days(), [])
