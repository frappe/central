# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The patches that end the per-address IPv4 subscriptions and then move the server's days to segments."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates
from central.billing.revenue import usage_segments
from central.billing.revenue.invoicing.lines import _subscription_clusters
from central.billing.revenue.usage_ledger import utc_day_start, write_central_days
from central.billing.revenue.usage_month import STATE
from central.billing.tests.test_ipv4_days import CLUSTER, JUNE, VM_PLAN, IPv4DaysTestCase, at
from central.billing.tests.utils import add_segment
from central.patches.v0_0 import bill_public_ipv4_per_day
from central.patches.v0_0 import move_public_ipv4_to_segments as segment_patch
from central.services.doctype.service.service import NETWORK_SERVICE, PUBLIC_IPV4_METER

CUTOVER_DAY = datetime.date(2026, 6, 20)


class AddressSubscriptionTestCase(IPv4DaysTestCase):
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

	def cancelled_at(self, subscription: str) -> list:
		return frappe.get_all(
			"Subscription Change",
			filters={"subscription": subscription, "change_type": "Cancelled"},
			pluck="effective_at",
		)


class TestIPv4CutoverInUSD(AddressSubscriptionTestCase):
	team = "team-ipv4-cutover-usd"
	server = "ipv4-cutover-usd-vm"
	currency = "USD"

	def test_the_cutover_bills_every_hour_once(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))

		bill_public_ipv4_per_day.close_address_subscriptions(utc_day_start("2026-06-20"))
		self.hold(at("2026-06-20"))

		invoice = self.invoice()
		# The server bills at 1000 a month; the per-address segment at 2.
		segment = [li for li in invoice.items if li.resource_type == "bundle" and li.rate == 2]
		[metered] = [li for li in invoice.items if li.resource_type == "IP"]
		hours = sum(_hours_billed(li) for li in segment) + metered.quantity * 30 * 24
		self.assertAlmostEqual(hours, 30 * 24, places=4)
		self.assertAlmostEqual(sum(li.amount for li in segment) + metered.amount, 2, places=2)
		self.assertFalse(frappe.db.get_value("Subscription", address, "enabled"))

	def test_an_address_subscription_opened_on_the_cutover_day_closes_where_it_opened(self):
		opened = at("2026-06-20", hours=3)
		address = self.address_subscription(opened)

		bill_public_ipv4_per_day.close_address_subscriptions(utc_day_start("2026-06-20"))

		self.assertEqual(self.cancelled_at(address), [frappe.utils.get_datetime(opened)])

	def test_a_closed_address_subscription_is_invoiced_in_the_server_region(self):
		subscription = frappe._dict(
			name=self.address_subscription(utc_day_start("2026-06-20")),
			server_id=None,
			vm_snapshot=None,
			public_ip_server=self.server,
		)

		self.assertEqual(_subscription_clusters([subscription]), {subscription.name: CLUSTER})


class CutoverPatchTestCase(AddressSubscriptionTestCase):
	"""The cutover patch run on day C, with the IP prices still on the rate card."""

	def setUp(self):
		super().setUp()
		# BillingTestCase's row sweep commits and would keep the patch's catalog rewrites; roll them back.
		self.addCleanup(frappe.db.rollback)
		# The patch sets the cutover day itself.
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", None)
		self.today = CUTOVER_DAY
		self.enterContext(patch.object(bill_public_ipv4_per_day, "utc_today", return_value=self.today))
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


class TestIPv4CutoverPatch(CutoverPatchTestCase):
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

	def test_an_address_paused_on_the_cutover_day_ends_at_the_pause(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))
		paused_at = frappe.utils.add_to_date(self.cutover, minutes=1)
		add_segment(address, "Paused", None, paused_at, currency=self.currency)

		bill_public_ipv4_per_day.execute()

		self.assertEqual(self.cancelled_at(address), [paused_at])

	def test_an_address_paused_and_resumed_on_the_cutover_day_ends_at_the_resume(self):
		address = self.address_subscription(utc_day_start("2026-06-01"))
		paused_at = frappe.utils.add_to_date(self.cutover, minutes=1)
		add_segment(address, "Paused", None, paused_at, currency=self.currency)
		resumed_at = frappe.utils.add_to_date(self.cutover, hours=2)
		add_segment(address, "Resumed", 2, resumed_at, currency=self.currency)

		bill_public_ipv4_per_day.execute()

		self.assertEqual(self.cancelled_at(address), [resumed_at])

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


class SegmentMigrationTestCase(AddressSubscriptionTestCase):
	"""Public IPv4 days written one per billed day, as before the segments, then moved by the patch."""

	def setUp(self):
		super().setUp()
		self.set_meter_aggregation("Level")

	def write_days(self, *days: str) -> None:
		"""Write the day values the hourly sweep wrote, one for each day the server billed."""
		meter = frappe.get_doc("Service", NETWORK_SERVICE).get_meter(PUBLIC_IPV4_METER)
		subject = frappe._dict(external_id=self.server, team=self.team, subscription=self.subscription)
		now = frappe.utils.now_datetime()
		write_central_days([meter.get_day_row(subject, day, 1, included=0, as_of=now) for day in days])

	def migrate(self, today: str, now=None) -> int:
		today = frappe.utils.getdate(today)
		cutover = usage_segments.cutover_day()
		segment_patch.SegmentMigration(cutover, today, now or at(str(today), hours=12)).run()
		segment_patch.set_state_meter()
		return segment_patch.reproject(cutover, today)

	def spans(self) -> list[tuple]:
		return [(row.starts_at, row.ends_at) for row in self.segments()]


class TestSegmentMigration(SegmentMigrationTestCase):
	def test_each_run_of_billed_days_becomes_a_closed_segment(self):
		self.write_days(*JUNE[:11], *JUNE[13:])

		self.migrate("2026-07-05")

		self.assertEqual(
			self.spans(),
			[
				(at("2026-06-01"), at("2026-06-12")),
				(at("2026-06-14"), at("2026-07-01")),
				(at("2026-07-05", hours=12), None),
			],
		)
		self.assertEqual({row.opened_source for row in self.segments()}, {usage_segments.MIGRATION})
		self.assertTrue(usage_segments.is_state_meter(NETWORK_SERVICE, PUBLIC_IPV4_METER))
		self.assertEqual(
			set(frappe.get_all("Usage Month", {"subject": self.server}, pluck="aggregation")),
			{STATE},
		)

	def test_a_holder_whose_days_reach_yesterday_stays_open_from_its_first_day(self):
		self.write_days(*JUNE[14:19])

		self.migrate("2026-06-20")

		self.assertEqual(self.spans(), [(at("2026-06-15"), None)])

	def test_a_released_address_whose_days_reach_today_ends_now(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)
		self.write_days(*JUNE[14:20])

		self.migrate("2026-06-20")

		self.assertEqual(self.spans(), [(at("2026-06-15"), at("2026-06-20", hours=12))])

	def test_a_holder_the_old_subscription_billed_on_the_cutover_day_starts_the_next_day(self):
		frappe.db.set_value("Service", NETWORK_SERVICE, "bill_from", "2026-06-20")
		address = self.address_subscription(utc_day_start("2026-06-01"))
		add_segment(address, "Paused", None, at("2026-06-20", hours=0.5), currency=self.currency)
		add_segment(address, "Resumed", 2, at("2026-06-20", hours=2), currency=self.currency)
		bill_public_ipv4_per_day.close_address_subscriptions(utc_day_start("2026-06-20"))

		self.migrate("2026-06-20")

		self.assertEqual(self.spans(), [(at("2026-06-21"), None)])
		self.assertEqual(self.days(), JUNE[20:])

	def test_running_the_patch_again_changes_nothing(self):
		frappe.db.set_default(segment_patch.SWEPT_DAY, "2026-06-09")
		self.write_days(*JUNE[:5])

		segment_patch.execute()
		segments = self.segments()
		segment_patch.execute()

		self.assertEqual(self.segments(), segments)
		self.assertFalse(frappe.db.get_default(segment_patch.SWEPT_DAY))

	def test_an_invoice_bills_the_same_before_and_after_the_patch(self):
		frappe.db.set_value("Virtual Machine", self.server, "public_ipv4", None)
		add_segment(self.subscription, "Paused", None, at("2026-06-11", hours=5))
		add_segment(self.subscription, "Resumed", 1000, at("2026-06-14", hours=20), plan=VM_PLAN)
		# The sweep wrote each day the server billed at some moment: the 11th and the 14th too.
		self.write_days(*JUNE[:11], *JUNE[13:])
		frappe.db.savepoint("before_draft")
		before = self.ip_line()
		frappe.db.rollback(save_point="before_draft")

		self.assertEqual(self.migrate("2026-07-05"), 0)
		# The draft then rebuilds every day from the segments alone.
		frappe.db.delete("Usage Month", {"service": NETWORK_SERVICE, "subject": self.server})

		after = self.ip_line()
		self.assertEqual((after.quantity, after.amount), (before.quantity, before.amount))
		self.assertAlmostEqual(after.quantity, 28 / 30)


def _hours_billed(line) -> float:
	"""The hours a fixed line covers: its hours on a part day, or its whole days."""
	return line.hours or line.days * 24
