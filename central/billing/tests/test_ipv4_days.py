# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A public IPv4 bills on its server for each UTC day the server held it, at the current IP rate."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.api.dashboard._shared import _describe_line
from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates
from central.billing.platform import readiness
from central.billing.revenue import public_ipv4_usage
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.usage_ledger import utc_day_start, utc_today
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import add_segment, make_plan, run_enqueued_inline, seed_running_resource
from central.patches.v0_0.bill_public_ipv4_per_day import close_address_subscriptions
from central.services.doctype.service.service import NETWORK_SERVICE

CLUSTER = "ap-south-1"
VM_PLAN = "ipv4-days-vm-plan"
ADDRESS = "203.0.113.20"
JUNE = [f"2026-06-{day:02d}" for day in range(1, 31)]


class IPv4DaysTestCase(IntegrationTestCase):
	"""A running server, billed all of June, that holds one public IPv4."""

	team = "team-ipv4-days"
	server = "ipv4-days-vm"
	currency = "INR"

	def setUp(self):
		frappe.db.delete("Virtual Machine", {"team": self.team})
		self.addCleanup(frappe.db.delete, "Virtual Machine", {"team": self.team})
		# The cutover patch sets the first billed day; these tests bill June.
		bill_from = frappe.db.get_value("Service", NETWORK_SERVICE, "bill_from")
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
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
		rows = frappe.get_all(
			"Usage Day",
			filters={"service": NETWORK_SERVICE, "subject": self.server},
			pluck="day",
			order_by="day",
		)
		return [str(day) for day in rows]

	def invoice(self):
		return frappe.get_doc("Invoice", generate_team_invoice(self.team, "2026-06-01", "2026-06-30"))

	def ip_line(self):
		[line] = [li for li in self.invoice().items if li.resource_type == "IP"]
		return line

	def readiness_details(self) -> list[str]:
		return [v.detail for v in readiness.check_public_ipv4_is_billed() if v.subject == self.server]


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
		self.assertEqual(frappe.db.get_value("Usage Day", {"subject": self.server}, "quantity"), 1)

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
		swept = frappe.db.get_default(public_ipv4_usage.SWEPT_DAY)
		self.addCleanup(frappe.db.set_default, public_ipv4_usage.SWEPT_DAY, swept)
		frappe.db.set_default(public_ipv4_usage.SWEPT_DAY, "2026-06-09")

		self.sweep("2026-06-11")
		self.assertEqual(self.days(), ["2026-06-10", "2026-06-11"])

		# Later runs that day write only today, so an address attached today never bills yesterday.
		frappe.db.delete("Usage Day", {"subject": self.server, "day": "2026-06-10"})
		self.sweep("2026-06-11")
		self.assertEqual(self.days(), ["2026-06-11"])

	def test_a_terminated_server_is_not_swept(self):
		frappe.db.set_value("Virtual Machine", self.server, "status", "Terminated")

		self.sweep("2026-06-11")

		self.assertEqual(self.days(), [])

	def sweep(self, day: str) -> None:
		with patch.object(public_ipv4_usage, "utc_today", return_value=frappe.utils.getdate(day)):
			public_ipv4_usage.read_public_ipv4()

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
		address = self.address_subscription(start="2026-06-01")

		close_address_subscriptions(utc_day_start("2026-06-20"))
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
		address = self.address_subscription(start=opened)

		close_address_subscriptions(utc_day_start("2026-06-20"))

		cancelled = frappe.db.get_value(
			"Subscription Change", {"subscription": address, "change_type": "Cancelled"}, "effective_at"
		)
		self.assertEqual(cancelled, frappe.utils.get_datetime(opened))

	def fixed_lines(self, invoice) -> list:
		return [li for li in invoice.items if li.resource_type == "bundle"]

	def address_subscription(self, start) -> str:
		"""A per-address subscription of the kind billed before the cutover, opened as a UTC day starts."""
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
		effective_at = utc_day_start(start) if len(str(start)) == 10 else start
		add_segment(address.name, "Created", 2, effective_at, currency="USD")
		return address.name


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


class TestIPv4Readiness(IPv4DaysTestCase):
	def test_readiness_lists_a_server_with_no_day_for_yesterday(self):
		self.assertIn("no usage for", " ".join(self.readiness_details()))

		self.write(str(utc_today() - datetime.timedelta(days=1)))

		self.assertEqual(self.readiness_details(), [])


def _hours_billed(line) -> float:
	"""The hours a fixed line covers: its hours on a part day, or its whole days."""
	return line.hours or line.days * 24
