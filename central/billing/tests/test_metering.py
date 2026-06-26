# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central metered ingestion + metered line items (issue #12)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue import invoicing, metering
from central.billing.platform.sync import receive_meter_rollups, receive_usage_events
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_metered_plan,
	make_plan,
)

TEAM = "team-meter"
CLUSTER = "ap-south-1"
PLAN = "bundle-meter-test"
RESOURCE = "srv-meter-1"


def meter(key_suffix, qty, resource_type="Transfer", meter_type="Counter"):
	return {
		"resource_id": RESOURCE,
		"resource_type": resource_type,
		"meter_type": meter_type,
		"period_start": "2026-06-01 00:00:00",
		"period_end": "2026-06-30 23:59:59",
		"quantity": qty,
		"unit": "GB",
		"idempotency_key": f"{RESOURCE}:{meter_type}:2026-06-01",
		"status": "open",
	}


def provision(rate=1000):
	receive_usage_events(
		[
			{
				"event_id": "ev-meter",
				"team": TEAM,
				"resource_id": RESOURCE,
				"cluster": CLUSTER,
				"plan": PLAN,
				"shown_rate": rate,
				"currency": "INR",
				"event_type": "subscribed",
				"effective_from": "2026-06-01 00:00:00",
				"effective_to": None,
			}
		]
	)


class MeteringTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		# Plan includes a 100 GB transfer allowance; metered plan bills 0.5/GB overage.
		make_plan(
			PLAN,
			includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}],
		)
		make_metered_plan(
			"meter-transfer",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		self._purge()
		provision()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Usage Rollup", "Price Lock", "Invoice"):
			frappe.db.delete(dt, {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()


class TestIngestRollup(MeteringTestBase):
	def test_rollup_stored_with_locked_terms(self):
		result = receive_meter_rollups([meter("a", 150)])
		self.assertEqual(len(result["acknowledged"]), 1)

		rollup = frappe.get_doc("Usage Rollup", {"resource_id": RESOURCE})
		self.assertEqual(rollup.team, TEAM)
		self.assertEqual(rollup.quantity, 150)
		self.assertEqual(rollup.locked_allowance, 100)  # from the locked plan includes
		self.assertEqual(rollup.locked_rate, 0.5)  # from the metered plan

	def test_repush_replaces_quantity_no_double_count(self):
		receive_meter_rollups([meter("a", 150)])
		receive_meter_rollups([meter("a", 220)])  # outage catch-up re-push

		self.assertEqual(frappe.db.count("Usage Rollup", {"resource_id": RESOURCE}), 1)
		self.assertEqual(
			frappe.db.get_value("Usage Rollup", {"resource_id": RESOURCE}, "quantity"), 220
		)

	def test_rollup_for_unprovisioned_resource_is_skipped(self):
		frappe.db.delete("Price Lock", {"team": TEAM})  # no active lock
		frappe.db.commit()
		result = receive_meter_rollups([meter("a", 150)])
		self.assertEqual(result["acknowledged"], [])
		self.assertEqual(frappe.db.count("Usage Rollup", {"resource_id": RESOURCE}), 0)


class TestMeteredLineItems(MeteringTestBase):
	def test_overage_billed_above_allowance(self):
		receive_meter_rollups([meter("a", 150)])  # 150 GB used, 100 allowed
		lines = metering.metered_line_items(TEAM, CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["quantity"], 50)  # max(0, 150-100)
		self.assertEqual(lines[0]["amount"], 25.0)  # 50 * 0.5

	def test_within_allowance_bills_nothing(self):
		receive_meter_rollups([meter("a", 80)])  # under the 100 GB allowance
		lines = metering.metered_line_items(TEAM, CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(lines, [])

	def test_draft_invoice_includes_fixed_and_metered_lines(self):
		receive_meter_rollups([meter("a", 150)])
		sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		# Full-June fixed segment at ₹1000/mo (authored as the run-segment billing
		# day-weights over), alongside the metered overage.
		add_segment(sub, "Created", 1000, "2026-06-01 00:00:00")
		name = invoicing.generate_draft_invoice(sub, "2026-06-01", "2026-06-30")
		inv = frappe.get_doc("Invoice", name)

		resource_types = sorted(li.resource_type for li in inv.items)
		self.assertIn("Transfer", resource_types)  # metered line present
		self.assertIn("bundle", resource_types)  # fixed line present
		# subtotal = fixed (full month 1000) + metered overage (25)
		self.assertEqual(inv.subtotal, 1025.0)
