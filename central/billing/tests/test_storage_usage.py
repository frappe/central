# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Object storage bills by the GB-month, from a daily reading of each team's buckets."""

from unittest.mock import patch

import frappe

from central.billing.catalog.subscriptions import provision_service_subscription
from central.billing.platform import invariants, readiness
from central.billing.revenue import storage_usage
from central.billing.revenue.invoicing.generate import rate_team_period, team_clusters
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	complete_billing_profile,
	ensure_team,
	give_team_a_card,
	make_plan,
)

TEAM = "team-storage-usage"
CLUSTER = "ap-south-1"
PLAN = "storage-usage-plan"
GIB = 1024**3
STORAGE_PLAN = [{"resource_type": "Storage", "quantity": 0, "unit": "GB"}]


class TestStorageUsage(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Team Service", {"team": TEAM})
		self.addCleanup(frappe.db.delete, "Team Service", {"team": TEAM})
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		give_team_a_card(TEAM)
		_clear_metered_plans("Storage", keep=PLAN)
		make_plan(
			PLAN,
			category="Remote Storage",
			includes=STORAGE_PLAN,
			rates=[{"currency": "INR", "cluster": CLUSTER, "rate": 2}],
		)
		self.subscription = provision_service_subscription(
			TEAM, PLAN, cluster=CLUSTER, start_date="2026-06-01"
		)["subscription"]
		bucket = frappe.get_doc(
			{
				"doctype": "Team Service",
				"team": TEAM,
				"add_on_service": "storage",
				"region": CLUSTER,
				"bucket_name": "team-storage-usage-bucket",
				"status": "Active",
				"subscription": self.subscription,
			}
		)
		bucket.db_insert()  # Skips before_insert, which would create the bucket in Cargo.

	def _read(self, day: str, gib: float):
		with patch(
			"central.services.doctype.team_service.team_service.TeamService.get_usage",
			return_value={"used_bytes": gib * GIB},
		):
			return storage_usage.record_storage_usage(day)

	def _rollup(self):
		return frappe.get_all(
			"Usage Rollup",
			filters={"team": TEAM, "resource_type": "Storage"},
			fields=["quantity", "sequence"],
		)

	def test_each_day_adds_its_share_of_the_month(self):
		self._read("2026-06-01", 30)
		self._read("2026-06-02", 60)
		[rollup] = self._rollup()
		self.assertAlmostEqual(rollup.quantity, 3.0)  # (30 + 60) / 30 days
		self.assertEqual(rollup.sequence, 2)

	def test_a_second_reading_the_same_day_adds_nothing(self):
		self._read("2026-06-01", 30)
		self._read("2026-06-01", 30)
		self.assertAlmostEqual(self._rollup()[0].quantity, 1.0)

	def test_a_missed_day_is_billed_at_the_next_reading(self):
		self._read("2026-06-01", 30)
		self._read("2026-06-03", 60)  # 2 June was never read
		self.assertAlmostEqual(self._rollup()[0].quantity, 5.0)  # (30 + 60 + 60) / 30 days

	def test_a_subscription_started_mid_month_bills_from_its_start(self):
		frappe.db.set_value("Subscription", self.subscription, "start_date", "2026-06-16")
		self._read("2026-06-16", 30)
		self.assertAlmostEqual(self._rollup()[0].quantity, 1.0)  # one day, not sixteen

	def test_the_invoice_bills_the_gb_month_at_the_current_rate(self):
		for day in range(1, 31):
			self._read(f"2026-06-{day:02d}", 100)
		rated = rate_team_period(TEAM, "2026-06-01", "2026-06-30")
		storage = [line for line in rated.payload["items"] if line.get("resource_type") == "Storage"]
		self.assertAlmostEqual(sum(frappe.utils.flt(line["amount"]) for line in storage), 200.0)

	def test_a_service_region_counts_as_a_team_cluster(self):
		self.assertIn(CLUSTER, team_clusters(TEAM))

	def test_a_missed_reading_is_flagged(self):
		with patch("frappe.utils.getdate", return_value=frappe.utils.getdate("2026-06-05")):
			found = [
				v
				for v in invariants.audit(only="M1", checks=readiness.CHECKS)
				if v.subject == self.subscription
			]
		self.assertEqual(len(found), 1)
