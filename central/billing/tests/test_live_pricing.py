# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Live-priced snapshot metered plan (issue #32 / ADR 0002, ADR 0008).

Most metered plans grandfather their rate at provision. Depreciating storage would
strand a customer on a stale-high rate, so a `Live` metered plan reads the CURRENT
Catalog Rate each billing period and has NO allowance. A snapshot is its own
resource_id from birth, so it survives VM termination (no active price-lock
required to bill it).
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue import metering
from central.billing.catalog.pricing import set_catalog_rates
from central.billing.platform.sync import receive_meter_rollups
from central.billing.tests.utils import ensure_team, make_metered_plan

TEAM = "team-live"
CLUSTER = "ap-south-1"


def snapshot_meter(resource_id, qty, currency="INR"):
	return {
		"resource_id": resource_id,
		"resource_type": "Snapshot",
		"meter_type": "Gauge",
		"period_start": "2026-06-01 00:00:00",
		"period_end": "2026-06-30 23:59:59",
		"quantity": qty,
		"unit": "GB-day",
		"team": TEAM,
		"cluster": CLUSTER,
		"currency": currency,
		"idempotency_key": f"{resource_id}:gauge:2026-06-01",
	}


class LivePricingTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_metered_plan(
			"meter-snapshot",
			resource_type="Snapshot",
			pricing_mode="Live",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.10}],
		)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Usage Rollup", "Invoice"):
			frappe.db.delete(dt, {"team": TEAM})
		frappe.db.commit()


class TestLiveSnapshot(LivePricingTestBase):
	def test_bills_at_current_rate_not_locked(self):
		receive_meter_rollups([snapshot_meter("snap-1", 100)])  # 100 GB-days

		lines = metering.metered_line_items(TEAM, CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["amount"], 10.0)  # 100 * 0.10 (current rate)

		# Storage depreciates: drop the catalog rate. The bill follows it down —
		# the rate is read live, never locked at ingest.
		set_catalog_rates("Plan", "meter-snapshot", [{"cluster": "", "currency": "INR", "rate": 0.08}])
		lines = metering.metered_line_items(TEAM, CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(lines[0]["amount"], 8.0)  # 100 * 0.08, not the old 0.10

	def test_ingests_without_price_lock(self):
		# No open billing segment exists for the snapshot's resource_id (its own id from
		# birth; the VM may even be terminated). A live add-on still ingests.
		result = receive_meter_rollups([snapshot_meter("snap-orphan", 50)])
		self.assertEqual(len(result["acknowledged"]), 1)
		self.assertTrue(frappe.db.exists("Usage Rollup", {"resource_id": "snap-orphan"}))

	def test_no_allowance_bills_all_gb_days(self):
		receive_meter_rollups([snapshot_meter("snap-2", 30)])  # small usage, no free tier
		lines = metering.metered_line_items(TEAM, CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(lines[0]["quantity"], 30.0)  # nothing free — every GB-day bills
		self.assertEqual(lines[0]["amount"], 3.0)  # 30 * 0.10
