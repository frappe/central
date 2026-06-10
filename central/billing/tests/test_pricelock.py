# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central price-lock ledger + usage-event ingestion (issue #03)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.revenue.pricelock import get_locked_rate
from central.billing.catalog.pricing import set_catalog_rates
from central.billing.platform.sync import receive_usage_events
from central.billing.tests.utils import ensure_team, make_plan

PLAN = "bundle-lock-test"
TEAM = "team-lock"


def event(event_id, resource_id, rate, event_type="subscribed", cluster=None, currency="USD"):
	return {
		"event_id": event_id,
		"team": "team-lock",
		"resource_id": resource_id,
		"cluster": cluster,
		"plan": PLAN,
		"shown_rate": rate,
		"currency": currency,
		"event_type": event_type,
		"effective_from": str(frappe.utils.now_datetime()),
		"effective_to": None,
	}


class PriceLockTestBase(IntegrationTestCase):
	def setUp(self):
		# Global USD rate = 40, INR = 3200.
		ensure_team(TEAM)
		make_plan(PLAN)
		for name in frappe.get_all("Price Lock", filters={"team": "team-lock"}, pluck="name"):
			frappe.delete_doc("Price Lock", name, force=True)


class TestReceiveUsageEvents(PriceLockTestBase):
	def test_subscribed_event_writes_lock_keyed_by_resource(self):
		result = receive_usage_events([event("evt-1", "srv-A", 40)])

		self.assertEqual(result["acknowledged"], ["evt-1"])
		lock = frappe.get_doc("Price Lock", {"source_event_id": "evt-1"})
		self.assertEqual(lock.resource_id, "srv-A")
		self.assertEqual(lock.locked_rate, 40)
		self.assertFalse(lock.discrepancy)
		self.assertEqual(get_locked_rate("srv-A"), 40)

	def test_ingestion_is_idempotent_on_event_id(self):
		receive_usage_events([event("evt-1", "srv-A", 40)])
		result = receive_usage_events([event("evt-1", "srv-A", 40)])  # replay

		self.assertEqual(result["acknowledged"], ["evt-1"])  # re-acked
		self.assertEqual(frappe.db.count("Price Lock", {"source_event_id": "evt-1"}), 1)

	def test_destroy_reprovision_yields_a_new_lock(self):
		receive_usage_events([event("evt-1", "srv-A", 40)])
		# Same bundle, different physical resource id → a fresh lock.
		receive_usage_events([event("evt-2", "srv-B", 40)])

		self.assertEqual(frappe.db.count("Price Lock", {"team": "team-lock"}), 2)
		self.assertEqual(get_locked_rate("srv-B"), 40)

	def test_shown_rate_differing_from_central_is_locked_and_flagged(self):
		# Customer was shown 35 though Central currently resolves 40.
		result = receive_usage_events([event("evt-d", "srv-D", 35)])

		self.assertEqual(result["acknowledged"], ["evt-d"])
		lock = frappe.get_doc("Price Lock", {"source_event_id": "evt-d"})
		self.assertEqual(lock.locked_rate, 35)  # the shown rate is honoured
		self.assertTrue(lock.discrepancy)
		self.assertEqual(lock.central_rate, 40)
		self.assertEqual(get_locked_rate("srv-D"), 35)

	def test_locked_rate_survives_live_catalog_change(self):
		receive_usage_events([event("evt-1", "srv-A", 40)])
		# Admin raises the live USD rate to 80 (edits the plan's Catalog Rate).
		set_catalog_rates("Plan", PLAN, [{"cluster": "", "currency": "USD", "rate": 80}])

		self.assertEqual(get_locked_rate("srv-A"), 40)  # the lock is untouched

	def test_changed_closes_old_lock_and_opens_new(self):
		receive_usage_events([event("evt-1", "srv-A", 40)])
		receive_usage_events([event("evt-2", "srv-A", 60, event_type="changed")])

		# Two locks for the resource; only the latest is active.
		self.assertEqual(frappe.db.count("Price Lock", {"resource_id": "srv-A"}), 2)
		self.assertEqual(get_locked_rate("srv-A"), 60)

	def test_cancelled_closes_the_active_lock(self):
		receive_usage_events([event("evt-1", "srv-A", 40)])
		receive_usage_events([event("evt-2", "srv-A", 40, event_type="Cancelled")])

		self.assertIsNone(get_locked_rate("srv-A"))  # nothing active
