# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import ensure_atlas_instance, ensure_team, make_plan

EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestSubscription(IntegrationTestCase):
	"""
	Integration tests for Subscription.
	Use this class for testing interactions between multiple components.
	"""

	def setUp(self):
		self.team = ensure_team("team-sub-doctype")
		self.plan = make_plan("plan-sub-doctype-a")
		self.plan_b = make_plan("plan-sub-doctype-b")
		ensure_atlas_instance("ap-south-1")
		if not frappe.db.exists("Asset", "vm-sub-doctype"):
			frappe.get_doc(
				{
					"doctype": "Asset",
					"resource_id": "vm-sub-doctype",
					"team": self.team,
					"cluster": "ap-south-1",
					"status": "Pending",
				}
			).insert()
		self.asset = "vm-sub-doctype"
		self._cleanup_subscriptions()

	def tearDown(self):
		self._cleanup_subscriptions()

	def _cleanup_subscriptions(self):
		for sub in frappe.get_all("Subscription", filters={"team": self.team}, pluck="name"):
			for change in frappe.get_all("Subscription Change", filters={"subscription": sub}, pluck="name"):
				frappe.delete_doc("Subscription Change", change, force=True)
			frappe.delete_doc("Subscription", sub, force=True)

	def _make_subscription(self, enabled=1, plan=None):
		return frappe.get_doc(
			{
				"doctype": "Subscription",
				"team": self.team,
				"asset_id": self.asset,
				"plan": plan or self.plan,
				"enabled": enabled,
			}
		).insert()

	def test_blocks_duplicate_enabled_subscription_for_same_team_and_asset(self):
		self._make_subscription(enabled=1)
		with self.assertRaises(frappe.DuplicateEntryError):
			self._make_subscription(enabled=1)

	def test_disabled_duplicate_does_not_raise(self):
		self._make_subscription(enabled=1)
		duplicate = self._make_subscription(enabled=0)
		self.assertTrue(duplicate.name)

	def test_after_insert_logs_created_change(self):
		sub = self._make_subscription()
		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub.name, "change_type": "Created"},
			fields=["new_value"],
		)
		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0].new_value, self.plan)

	def test_enable_sets_flag(self):
		sub = self._make_subscription(enabled=0)
		sub.enable()
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "enabled"), 1)

	def test_disable_sets_flag(self):
		sub = self._make_subscription(enabled=1)
		sub.disable()
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "enabled"), 0)

	def test_plan_update_logs_plan_changed(self):
		sub = self._make_subscription()
		sub.plan = self.plan_b
		sub.save()

		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub.name, "change_type": "Plan Changed"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0].old_value, self.plan)
		self.assertEqual(changes[0].new_value, self.plan_b)

	def test_save_without_plan_change_does_not_log(self):
		sub = self._make_subscription()
		sub.start_date = frappe.utils.nowdate()
		sub.save()

		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub.name, "change_type": "Plan Changed"},
		)
		self.assertEqual(len(changes), 0)
