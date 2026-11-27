# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The patch that ends the per-address IPv4 subscriptions where the server's days begin."""

import datetime
from unittest.mock import patch

import frappe

from central.billing.catalog.pricing import get_catalog_rates, set_catalog_rates
from central.billing.revenue.invoicing.lines import _subscription_clusters
from central.billing.revenue.usage_ledger import utc_day_start
from central.billing.tests.test_ipv4_days import CLUSTER, IPv4DaysTestCase, at
from central.billing.tests.utils import add_segment
from central.patches.v0_0 import bill_public_ipv4_per_day
from central.services.doctype.service.service import NETWORK_SERVICE

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


def _hours_billed(line) -> float:
	"""The hours a fixed line covers: its hours on a part day, or its whole days."""
	return line.hours or line.days * 24
