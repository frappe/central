# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Invoices from month rows bill what the day ledger billed: storage, AI in INR and public IPv4."""

from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.revenue import storage_bridge
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.tests.test_ai_billing import TEAM_INR, AIBillingCase, feed, forget_rate_readings, rate_on
from central.billing.tests.test_bundled_buckets import (
	CLUSTER,
	SERVER,
	STORAGE_PLAN,
	TEAM,
	VM_PLAN,
	BundledServerFixture,
)
from central.billing.tests.test_ipv4_days import JUNE, IPv4DaysTestCase
from central.billing.tests.utils import (
	DEFAULT_INCLUDES,
	BillingTestCase,
	add_segment,
	give_team_a_card,
	make_plan,
	usage_days,
)
from central.services.doctype.team_service.team_service import TeamService

TEAM_BUCKET = "team-bundled-bucket-media"
GB = 1_000_000_000
JUNE_PERIOD = ("2026-06-01", "2026-06-30")
JULY_PERIOD = ("2026-07-01", "2026-07-31")


class StorageMonthsFixture(BundledServerFixture):
	"""A server whose backup bucket has a daily bundle, and a team bucket of the same team."""

	def set_up_storage_months(self):
		self.set_up_bundled_server()
		give_team_a_card(TEAM)
		frappe.db.delete("Team Service", {"team": TEAM})
		self.addCleanup(frappe.db.delete, "Team Service", {"team": TEAM})
		subscription = provision_service_subscription(
			TEAM, STORAGE_PLAN, cluster=CLUSTER, start_date="2026-06-01"
		)
		self.team_subject = frappe.db.get_value(
			"Subscription", subscription["subscription"], "service_subject"
		)
		self.team_bucket = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": TEAM,
				"add_on_service": "storage",
				"region": CLUSTER,
				"bucket_name": TEAM_BUCKET,
				"external_id": TEAM_BUCKET,
				"status": "Active",
				"subscription": subscription["subscription"],
				"creation": "2026-06-01 00:00:00",
			}
		)
		self.team_bucket.db_insert()  # Skips before_insert, which would create the bucket in Cargo.

	def read_team_bucket(self, day: str, gb: float) -> None:
		with (
			patch.object(storage_bridge, "utc_today", return_value=frappe.utils.getdate(day)),
			patch.object(TeamService, "get_usage", return_value={"used_bytes": gb * GB}),
		):
			storage_bridge.RegionRead("test-run", CLUSTER).start(1)
			storage_bridge.read_page("test-run", CLUSTER, [self.team_bucket.name])

	def read_june(self) -> None:
		"""100 GB in the backup bucket, 40 GB included until a resize to 200 GB on the 16th; 30 GB in the team bucket."""
		for day in range(1, 31):
			if day == 16:
				plan = make_plan(
					f"{VM_PLAN}-200",
					includes=[*DEFAULT_INCLUDES, {"resource_type": "Storage", "quantity": 200, "unit": "GB"}],
				)
				frappe.db.set_value("Subscription", self.subscription, "plan", plan)
				add_segment(self.subscription, "Plan Changed", 1000, "2026-06-16 00:00:00", plan=plan)
			self.read(f"2026-06-{day:02d}", 100)
			self.read_team_bucket(f"2026-06-{day:02d}", 30)

	def storage_amounts(self, period) -> dict:
		invoice = generate_team_invoice(TEAM, *period)
		lines = frappe.get_all(
			"Invoice Line Item",
			filters={"parent": invoice, "resource_type": "Storage"},
			fields=["subscription_resource", "amount"],
		)
		return {line.subscription_resource: line.amount for line in lines}


class TestStorageFromMonthRows(StorageMonthsFixture, BillingTestCase):
	def setUp(self):
		self.set_up_storage_months()

	def test_each_bucket_bills_the_amount_the_day_ledger_billed(self):
		self.read_june()
		# 60 GB over the bundle for 15 of 30 days, then none; 30 GB all month with no bundle; 2.5 a GB-month.
		self.assertEqual(self.storage_amounts(JUNE_PERIOD), {SERVER: 75.0, self.team_subject: 75.0})

	def test_the_invoice_stamps_every_day_and_each_rated_month(self):
		self.read_june()
		self.storage_amounts(JUNE_PERIOD)
		invoice = frappe.db.get_value("Invoice", {"team": TEAM, "period_start": JUNE_PERIOD[0]})
		self.assertEqual({day.invoice for day in usage_days(team=TEAM)}, {invoice})
		rated = frappe.get_all(
			"Usage Month",
			filters={"team": TEAM, "counted_at": ["is", "set"]},
			fields=["invoice", "billed_quantity"],
		)
		self.assertEqual(
			sorted((month.invoice, month.billed_quantity) for month in rated), [(invoice, 30)] * 2
		)


class TestAIFromMonthRows(AIBillingCase):
	def test_an_inr_model_below_zero_carries_into_the_next_month_at_its_rate(self):
		self.land(TEAM_INR, "2026-06-10", {"gpt-4o": 2.0, "claude-sonnet": 0.5})
		self.land(TEAM_INR, "2026-06-12", {"claude-sonnet": -1.0})
		self.land(TEAM_INR, "2026-07-05", {"gpt-4o": 1.0, "claude-sonnet": 1.0})
		self.read("2026-06-10", "2026-06-12", "2026-07-05")

		with feed(rate_on("2026-06-01", 84.1)):
			june = self.invoice_lines(TEAM_INR)
		forget_rate_readings()
		with feed(rate_on("2026-07-01", 85.0)):
			july = self.invoice_lines(TEAM_INR, JULY_PERIOD)

		self.assertEqual(self.amounts(june), [("gpt-4o", 168.2)])
		# Claude nets -0.5 in June and +1.0 in July: 0.5 USD at July's rate.
		self.assertEqual(self.amounts(july), [("gpt-4o", 85.0), ("claude-sonnet", 42.5)])

	def amounts(self, lines) -> list:
		return [(line.description.split(" · ")[0], line.amount) for line in lines]


class TestPublicIPv4FromMonthRows(IPv4DaysTestCase):
	def test_an_address_held_all_month_bills_one_address_month(self):
		self.write(*JUNE)
		line = self.ip_line()
		self.assertEqual((line.quantity, line.amount), (1.0, 170.0))
		self.assertEqual({day.invoice for day in usage_days(subject=self.server)}, {line.parent})
