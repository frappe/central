# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The Price Lock retirement backfill (ADR 0010, #86).

Asserts the before→after mapping on seeded rows: an open lock whose resource's
subscription has no open billing segment gets a mirrored `Created` segment; a
subscription that already has an open segment is left untouched (idempotent)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.subscriptions import active_segment_for_resource
from central.billing.patches.v25_retire_price_lock.retire_price_lock import (
	backfill_open_locks_into_ledger,
)
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-retire-lock"
CLUSTER = "ap-south-1"
PLAN = "bundle-retire-lock"


class TestPriceLockBackfill(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_atlas_instance(CLUSTER)
		complete_billing_profile(TEAM, currency="INR")
		make_plan(PLAN)
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})

	def _lock(self, resource_id, rate=3200):
		return {
			"resource_id": resource_id, "team": TEAM, "plan": PLAN,
			"currency": "INR", "locked_rate": rate, "started_at": "2026-06-01 00:00:00",
		}

	def test_backfill_writes_segment_for_lock_without_open_segment(self):
		# A subscription whose auto 'Created' segment was cleared — a legacy lock with no
		# ledger segment.
		make_billing_subscription(TEAM, CLUSTER, PLAN, resource_id="srv-legacy")
		self.assertIsNone(active_segment_for_resource("srv-legacy"))

		written = backfill_open_locks_into_ledger(locks=[self._lock("srv-legacy", 3200)])
		self.assertEqual(written, 1)

		seg = active_segment_for_resource("srv-legacy")
		self.assertIsNotNone(seg)
		self.assertEqual(seg.locked_rate, 3200)
		self.assertEqual(seg.currency, "INR")

		# Idempotent: a second run over the same lock writes nothing.
		self.assertEqual(backfill_open_locks_into_ledger(locks=[self._lock("srv-legacy", 3200)]), 0)

	def test_backfill_skips_subscription_that_already_has_open_segment(self):
		# create_subscription writes an open 'Created' segment; backfill must not double it.
		from central.billing.catalog import subscriptions

		subscriptions.create_subscription(
			team=TEAM, cluster=CLUSTER, plan=PLAN, billing_cycle="Monthly", resource_id="srv-live"
		)
		before = frappe.db.count("Subscription Change", {"subscription": ["in",
			frappe.get_all("Subscription", {"team": TEAM}, pluck="name")]})

		self.assertEqual(backfill_open_locks_into_ledger(locks=[self._lock("srv-live", 999)]), 0)

		after = frappe.db.count("Subscription Change", {"subscription": ["in",
			frappe.get_all("Subscription", {"team": TEAM}, pluck="name")]})
		self.assertEqual(before, after)

	def test_backfill_skips_lock_with_no_subscription(self):
		self.assertEqual(backfill_open_locks_into_ledger(locks=[self._lock("srv-orphan")]), 0)
