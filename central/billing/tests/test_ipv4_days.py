# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A public IPv4 bills on its server for each UTC day the server held it, at the current IP rate."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.api.dashboard._shared import _describe_line
from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates
from central.billing.platform import readiness
from central.billing.revenue import public_ipv4_usage, usage_month
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.invoicing.lines import _subscription_clusters
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	make_plan,
	run_enqueued_inline,
	seed_running_resource,
	usage_days,
)
from central.patches.v0_0 import bill_public_ipv4_per_day
from central.services.doctype.service.service import NETWORK_SERVICE

CLUSTER = "ap-south-1"
VM_PLAN = "ipv4-days-vm-plan"
ADDRESS = "203.0.113.20"
JUNE = [f"2026-06-{day:02d}" for day in range(1, 31)]
CUTOVER_DAY = datetime.date(2026, 6, 20)
BEFORE_JUNE = datetime.date(2026, 1, 1)


class IPv4DaysTestCase(IntegrationTestCase):
	"""A running server, billed all of June, that holds one public IPv4."""

	team = "team-ipv4-days"
	server = "ipv4-days-vm"
	currency = "INR"

	def setUp(self):
		frappe.db.delete("Virtual Machine", {"team": self.team})
		self.addCleanup(frappe.db.delete, "Virtual Machine", {"team": self.team})
		# These tests bill June, so the cutover is set before it: no day is written without one.
		bill_from = frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from")
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", BEFORE_JUNE)
		self.addCleanup(frappe.db.set_value, "Service", NETWORK_SERVICE, "bill_from", bill_from)
		make_plan(VM_PLAN)
		self.subscription = seed_running_resource(
			self.team, self.server, CLUSTER, VM_PLAN, rate=1000, currency=self.currency
		)
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", ADDRESS)

	def write(self, *days: str, addresses: int = 1) -> None:
		for day in days:
			public_ipv4_usage.write_ipv4_days(day, {self.server: addresses})

	def days(self) -> list[str]:
		return [str(day.day) for day in usage_days(service=NETWORK_SERVICE, subject=self.server)]

	def forget_day(self, day: str) -> None:
		"""Remove one stored day, as if it had never been written."""
		month = frappe.get_doc("Usage Month", {"subject": self.server, "month": usage_month.month_of(day)})
		number = frappe.utils.getdate(day).day
		slots = frappe.parse_json(month.slots)
		slots.pop(str(number))
		mask = ~usage_month.bit(number)
		frappe.db.set_value(
			"Usage Month",
			month.name,
			{
				"filled": month.filled & mask,
				"open_days": month.open_days & mask,
				"slots": frappe.as_json(slots),
			},
		)

	def invoice(self):
		return frappe.get_doc("Invoice", generate_team_invoice(self.team, "2026-06-01", "2026-06-30"))

	def ip_line(self):
		[line] = [li for li in self.invoice().items if li.resource_type == "IP"]
		return line

	def readiness_details(self) -> list[str]:
		return [v.detail for v in readiness.check_public_ipv4_is_billed() if v.subject == self.server]

	def sweep(self, day: str) -> None:
		with patch.object(public_ipv4_usage, "utc_today", return_value=frappe.utils.getdate(day)):
			public_ipv4_usage.read_public_ipv4()

	def keep_swept_day(self) -> None:
		swept = frappe.db.get_default(public_ipv4_usage.SWEPT_DAY)
		self.addCleanup(frappe.db.set_default, public_ipv4_usage.SWEPT_DAY, swept)

	def address_subscription(self, start: datetime.datetime) -> str:
		"""A per-address subscription of the kind billed before the cutover, opened at `start`."""
		address = frappe.get_doc(
			{
				"doctype": "Subscription",
				"team": self.team,
				"public_ip_server": self.server,
				"pricing_mode": "Composed",
				"includes": [{"resource_type": "IP", "quantity": 1, "unit": "Nos"}],
				"billing_cycle": "Monthly",
				"account_standing": "Current",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.delete("Subscription Change", {"subscription": address.name})
		add_segment(address.name, "Created", 2, start, currency=self.currency)
		return address.name


class TestIPv4DayBilling(IPv4DaysTestCase):
	def test_ten_days_of_thirty_bill_a_third_of_an_address_month(self):
		self.write(*JUNE[:10])

		line = self.ip_line()
		self.assertAlmostEqual(line.quantity, 10 / 30)
		self.assertEqual(line.amount, frappe.utils.flt(170 * 10 / 30, 2))

	def test_the_line_names_the_plan_and_the_server(self):
		frappe.db.set_value("Virtual Machine", self.server, "title", "Web box")
		self.write(*JUNE[:3])

		row = _describe_line(self.team, self.ip_line(), ("2026-06-01", "2026-06-30"))
		self.assertEqual(row["item"], "Public IPv4 · Web box")
		self.assertTrue(row["detail"].startswith("Metered · "))

	def test_a_server_writes_one_day_however_often_it_is_read(self):
		self.write("2026-06-05", "2026-06-05")
		self.write("2026-06-05", addresses=0)

		self.assertEqual(self.days(), ["2026-06-05"])
		self.assertEqual([day.quantity for day in usage_days(subject=self.server)], [1])

	def test_an_address_held_for_part_of_a_day_bills_the_day(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)
		with (
			patch.object(public_ipv4_usage, "utc_today", return_value=datetime.date(2026, 6, 7)),
			patch("frappe.enqueue", side_effect=run_enqueued_inline),
		):
			self.observe(public_ipv4=ADDRESS)
			self.observe(public_ipv4=None)

		self.assertEqual(self.days(), ["2026-06-07"])
		self.assertAlmostEqual(self.ip_line().quantity, 1 / 30)

	def test_a_stopped_server_still_bills_its_address(self):
		frappe.db.set_value("Virtual Machine", self.server, "status", "Stopped")

		with patch.object(public_ipv4_usage, "utc_today", return_value=datetime.date(2026, 6, 3)):
			public_ipv4_usage.read_public_ipv4()

		self.assertIn("2026-06-03", self.days())

	def test_a_day_with_billing_paused_throughout_bills_nothing(self):
		# 00:00 IST on the 10th is 18:30 UTC on the 9th; billing resumes at 06:30 UTC on the 12th.
		add_segment(self.subscription, "Paused", None, "2026-06-10 00:00:00")
		add_segment(self.subscription, "Resumed", 1000, "2026-06-12 12:00:00", plan=VM_PLAN)

		self.write("2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12")

		self.assertEqual(self.days(), ["2026-06-09", "2026-06-12"])

	def test_a_server_with_no_open_segment_is_free_until_billing_starts(self):
		frappe.db.delete("Subscription Change", {"subscription": self.subscription})

		self.write("2026-06-14")
		self.assertEqual(self.days(), [])

		# A trial converts: the server's billing starts mid-day on the 15th.
		add_segment(self.subscription, "Created", 1000, "2026-06-15 12:00:00", plan=VM_PLAN)
		self.write("2026-06-14", "2026-06-15")
		self.assertEqual(self.days(), ["2026-06-15"])

	def test_the_termination_day_bills_once(self):
		add_segment(self.subscription, "Cancelled", None, "2026-06-20 10:00:00")

		self.write("2026-06-20", "2026-06-20", "2026-06-21")

		self.assertEqual(self.days(), ["2026-06-20"])

	def test_the_first_run_of_a_day_also_writes_the_day_before(self):
		self.keep_swept_day()
		frappe.db.set_default(public_ipv4_usage.SWEPT_DAY, "2026-06-09")

		self.sweep("2026-06-11")
		self.assertEqual(self.days(), ["2026-06-10", "2026-06-11"])

		# Later runs that day write only today, so an address attached today never bills yesterday.
		self.forget_day("2026-06-10")
		self.sweep("2026-06-11")
		self.assertEqual(self.days(), ["2026-06-11"])

	def test_a_failed_page_leaves_the_day_before_to_the_next_run(self):
		self.keep_swept_day()
		frappe.db.set_default(public_ipv4_usage.SWEPT_DAY, "2026-06-09")

		with patch.object(public_ipv4_usage, "write_central_days", side_effect=frappe.QueryTimeoutError):
			self.sweep("2026-06-11")
		self.assertEqual(frappe.db.get_default(public_ipv4_usage.SWEPT_DAY), "2026-06-09")

		self.sweep("2026-06-11")
		self.assertEqual(self.days(), ["2026-06-10", "2026-06-11"])
		self.assertEqual(frappe.db.get_default(public_ipv4_usage.SWEPT_DAY), "2026-06-11")

	def test_a_terminated_server_is_not_swept(self):
		frappe.db.set_value("Virtual Machine", self.server, "status", "Terminated")

		self.sweep("2026-06-11")

		self.assertEqual(self.days(), [])

	def observe(self, **state) -> None:
		server = frappe.get_doc("Virtual Machine", self.server)
		server.record_observed_state(state, frappe.utils.now_datetime())


class TestIPv4DayBillingInUSD(IPv4DaysTestCase):
	team = "team-ipv4-days-usd"
	server = "ipv4-days-usd-vm"
	currency = "USD"

	def test_an_address_held_all_month_bills_one_address_month(self):
		self.write(*JUNE)

		line = self.ip_line()
		self.assertAlmostEqual(line.quantity, 1)
		self.assertEqual(line.amount, 2)

	def test_the_cutover_bills_every_hour_once(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))

		bill_public_ipv4_per_day.close_address_subscriptions(utc_day_start("2026-06-20"))
		self.write(*JUNE[19:])

		invoice = self.invoice()
		# The server bills at 1000 a month; the per-address segment at 2.
		segment = [li for li in self.fixed_lines(invoice) if li.rate == 2]
		[metered] = [li for li in invoice.items if li.resource_type == "IP"]
		hours = sum(_hours_billed(li) for li in segment) + metered.quantity * 30 * 24
		self.assertAlmostEqual(hours, 30 * 24, places=4)
		self.assertAlmostEqual(sum(li.amount for li in segment) + metered.amount, 2, places=2)
		self.assertFalse(frappe.db.get_value("Subscription", address, "enabled"))

	def test_an_address_subscription_opened_on_the_cutover_day_closes_where_it_opened(self):
		opened = frappe.utils.add_to_date(utc_day_start("2026-06-20"), hours=3)
		address = self.address_subscription(opened)

		bill_public_ipv4_per_day.close_address_subscriptions(utc_day_start("2026-06-20"))

		cancelled = frappe.db.get_value(
			"Subscription Change", {"subscription": address, "change_type": "Cancelled"}, "effective_at"
		)
		self.assertEqual(cancelled, frappe.utils.get_datetime(opened))

	def test_a_closed_address_subscription_is_invoiced_in_the_server_region(self):
		subscription = frappe._dict(
			name=self.address_subscription(utc_day_start("2026-06-20")),
			server_id=None,
			vm_snapshot=None,
			public_ip_server=self.server,
		)

		self.assertEqual(_subscription_clusters([subscription]), {subscription.name: CLUSTER})

	def fixed_lines(self, invoice) -> list:
		return [li for li in invoice.items if li.resource_type == "bundle"]


class TestUnpricedIPv4(IPv4DaysTestCase):
	def setUp(self):
		super().setUp()
		plan = frappe.db.get_value("Plan Includes", {"resource_type": "IP", "parenttype": "Plan"}, "parent")
		self.ip_plan = plan
		rates = get_catalog_rates("Plan", plan)
		self.addCleanup(set_catalog_rates, "Plan", plan, [dict(row) for row in rates])
		set_catalog_rates("Plan", plan, [dict(row) for row in rates if row.currency != "INR"])

	def test_a_day_with_no_price_is_written_and_holds_the_draft(self):
		self.write(*JUNE[:10])
		self.assertEqual(len(self.days()), 10)

		with self.assertRaises(frappe.ValidationError):
			generate_team_invoice(self.team, "2026-06-01", "2026-06-30")
		self.assertFalse(frappe.db.exists("Invoice", {"team": self.team}))

		set_catalog_rates("Plan", self.ip_plan, [{"currency": "INR", "rate": 170}])
		self.assertAlmostEqual(self.ip_line().quantity, 10 / 30)

	def test_readiness_lists_the_unpriced_server(self):
		self.write(str(utc_today() - datetime.timedelta(days=1)))

		details = self.readiness_details()

		self.assertEqual(len(details), 1)
		self.assertIn("no price in INR", details[0])

	def test_readiness_skips_an_unpriced_server_with_no_address(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)

		self.assertEqual(self.readiness_details(), [])


class TestIPv4Readiness(IPv4DaysTestCase):
	def test_readiness_skips_a_priced_server_with_no_day_yet(self):
		self.assertEqual(self.readiness_details(), [])


class TestIPv4Cutover(IPv4DaysTestCase):
	"""The patch that moves public IPv4 from per-address subscriptions to day values."""

	def setUp(self):
		super().setUp()
		# BillingTestCase's row sweep commits and would keep the patch's catalog rewrites; roll them back.
		self.addCleanup(frappe.db.rollback)
		# The patch sets the cutover day itself.
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
		self.keep_swept_day()
		self.today = CUTOVER_DAY
		self.enterContext(patch.object(bill_public_ipv4_per_day, "utc_today", return_value=self.today))
		self.enterContext(patch.object(public_ipv4_usage, "utc_today", return_value=self.today))
		self.cutover = utc_day_start(self.today)
		self.old_rates = [
			{"currency": "INR", "rate": 180, "cluster": None},
			{"currency": "INR", "rate": 150, "cluster": CLUSTER},
			{"currency": "USD", "rate": 3, "cluster": None},
		]
		set_catalog_rates("Resource Type", "IP", self.old_rates)
		frappe.db.delete("Catalog Rate", {"priced_doctype": "Plan", "priced_for": "public-ipv4"})
		frappe.db.delete("Plan Includes", {"parenttype": "Plan", "parent": "public-ipv4"})
		frappe.db.delete("Plan", "public-ipv4")

	def test_the_patch_moves_the_ip_price_onto_the_plan(self):
		bill_public_ipv4_per_day.execute()

		rates = {
			(row.currency, row.cluster or None): row.rate for row in get_catalog_rates("Plan", "public-ipv4")
		}
		self.assertEqual(rates, {(row["currency"], row["cluster"]): row["rate"] for row in self.old_rates})
		self.assertEqual(get_catalog_rates("Resource Type", "IP"), [])

	def test_the_patch_ends_an_address_subscription_where_the_days_begin(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))

		bill_public_ipv4_per_day.execute()

		self.assertEqual(frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"), self.today)
		self.assertEqual(self.cancelled_at(address), [self.cutover])
		self.assertFalse(frappe.db.get_value("Subscription", address, "enabled"))
		self.assertEqual(self.days(), [str(self.today)])

	def test_the_day_before_the_cutover_is_written_off(self):
		bill_public_ipv4_per_day.execute()
		frappe.db.set_default(public_ipv4_usage.SWEPT_DAY, "")

		self.sweep(str(self.today))

		yesterday = self.today - datetime.timedelta(days=1)
		self.assertEqual(self.days(), [str(yesterday), str(self.today)])
		self.assertTrue(usage_days(subject=self.server, day=yesterday)[0].written_off)

	def test_an_address_paused_on_the_cutover_day_bills_that_day_only_on_its_old_subscription(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))
		paused_at = frappe.utils.add_to_date(self.cutover, minutes=1)
		add_segment(address, "Paused", None, paused_at, currency=self.currency)

		bill_public_ipv4_per_day.execute()
		self.sweep(str(self.today))

		self.assertEqual(self.cancelled_at(address), [paused_at])
		self.assertNotIn(str(self.today), self.days())

	def test_an_address_paused_and_resumed_on_the_cutover_day_bills_no_hour_after_the_resume(self):
		"""The decided gap: the hours after the resume on day C are not billed, and none bill twice."""
		address = self.address_subscription(utc_day_start("2026-06-01"))
		paused_at = frappe.utils.add_to_date(self.cutover, minutes=1)
		add_segment(address, "Paused", None, paused_at, currency=self.currency)
		resumed_at = frappe.utils.add_to_date(self.cutover, hours=2)
		add_segment(address, "Resumed", 2, resumed_at, currency=self.currency)

		bill_public_ipv4_per_day.execute()
		self.sweep(str(self.today))

		self.assertEqual(self.cancelled_at(address), [resumed_at])
		self.assertNotIn(str(self.today), self.days())

	def test_an_address_subscription_opened_after_the_cutover_still_bills_the_day(self):
		address = self.address_subscription(frappe.utils.add_to_date(self.cutover, hours=3))

		bill_public_ipv4_per_day.execute()
		self.sweep(str(self.today))

		# It opens and closes at the same moment, so it billed no hour of the day.
		self.assertEqual(len(self.cancelled_at(address)), 1)
		self.assertIn(str(self.today), self.days())

	def test_a_day_after_the_cutover_never_reads_the_address_subscriptions(self):
		self.address_subscription(utc_day_start("2026-06-01"))
		bill_public_ipv4_per_day.execute()
		tomorrow = str(self.today + datetime.timedelta(days=1))

		with patch.object(public_ipv4_usage, "_address_changes") as address_changes:
			self.write(tomorrow)

		address_changes.assert_not_called()
		self.assertIn(tomorrow, self.days())

	def test_no_day_is_written_until_the_patch_sets_the_cutover_day(self):
		self.queue_today()
		self.sweep(str(self.today))
		self.assertEqual(self.days(), [])

		bill_public_ipv4_per_day.execute()
		self.clear_days()
		self.queue_today()
		self.assertEqual(self.days(), [str(self.today)])

		self.clear_days()
		frappe.db.set_default(public_ipv4_usage.SWEPT_DAY, str(self.today))
		self.sweep(str(self.today))
		self.assertEqual(self.days(), [str(self.today)])

	def test_the_patch_keeps_the_rates_when_no_plan_bills_ipv4(self):
		with patch.object(bill_public_ipv4_per_day, "metered_plan_for", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				bill_public_ipv4_per_day.execute()

		self.assertEqual(len(get_catalog_rates("Resource Type", "IP")), len(self.old_rates))

	def test_running_the_patch_again_changes_nothing(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))
		bill_public_ipv4_per_day.execute()
		rates = get_catalog_rates("Plan", "public-ipv4")

		bill_public_ipv4_per_day.execute()

		self.assertEqual(get_catalog_rates("Plan", "public-ipv4"), rates)
		self.assertEqual(self.cancelled_at(address), [self.cutover])
		self.assertEqual(self.days(), [str(self.today)])

	def queue_today(self) -> None:
		with patch("frappe.enqueue", side_effect=run_enqueued_inline):
			public_ipv4_usage.queue_today(self.server, 1)

	def clear_days(self) -> None:
		frappe.db.delete("Usage Month", {"service": NETWORK_SERVICE, "subject": self.server})

	def cancelled_at(self, subscription: str) -> list:
		return frappe.get_all(
			"Subscription Change",
			filters={"subscription": subscription, "change_type": "Cancelled"},
			pluck="effective_at",
		)


class TestIPv4BeforeTheCutover(IPv4DaysTestCase):
	"""A fresh install starts the days itself; a site not yet migrated writes none."""

	def test_a_fresh_install_bills_from_its_install_day(self):
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
		with patch.object(public_ipv4_usage, "utc_today", return_value=CUTOVER_DAY):
			public_ipv4_usage.start_on_install()

		self.assertEqual(frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"), CUTOVER_DAY)

	def test_a_fresh_install_runs_the_start_hook(self):
		self.assertIn(
			"central.billing.revenue.public_ipv4_usage.start_on_install", frappe.get_hooks("after_install")
		)

	def test_install_keeps_a_cutover_day_already_set(self):
		with patch.object(public_ipv4_usage, "utc_today", return_value=CUTOVER_DAY):
			public_ipv4_usage.start_on_install()

		self.assertEqual(frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from"), BEFORE_JUNE)

	def test_no_day_is_written_before_migrate_creates_the_service(self):
		# The deleted service must come back before the setUp cleanups run.
		self.addCleanup(frappe.db.rollback)
		frappe.db.delete("Service", NETWORK_SERVICE)

		self.write("2026-06-05")
		self.sweep("2026-06-11")

		self.assertEqual(self.days(), [])


def _hours_billed(line) -> float:
	"""The hours a fixed line covers: its hours on a part day, or its whole days."""
	return line.hours or line.days * 24
