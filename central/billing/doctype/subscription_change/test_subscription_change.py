# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import ensure_atlas_instance, ensure_team, make_plan

EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestSubscriptionChange(IntegrationTestCase):
	"""
	Integration tests for SubscriptionChange.
	Use this class for testing interactions between multiple components.
	"""

	def setUp(self):
		self.team = ensure_team("team-sub-change")
		self.plan = make_plan("plan-sub-change-a")
		self.plan_b = make_plan("plan-sub-change-b")
		ensure_atlas_instance("ap-south-1")
		if not frappe.db.exists("Asset", "vm-sub-change"):
			frappe.get_doc(
				{
					"doctype": "Asset",
					"resource_id": "vm-sub-change",
					"team": self.team,
					"cluster": "ap-south-1",
					"status": "Pending",
				}
			).insert()
		self.asset = "vm-sub-change"
		self._cleanup_subscriptions()

	def tearDown(self):
		self._cleanup_subscriptions()

	def _cleanup_subscriptions(self):
		for sub in frappe.get_all("Subscription", filters={"team": self.team}, pluck="name"):
			for change in frappe.get_all("Subscription Change", filters={"subscription": sub}, pluck="name"):
				frappe.delete_doc("Subscription Change", change, force=True)
			frappe.delete_doc("Subscription", sub, force=True)

	def _make_subscription(self, plan=None):
		return frappe.get_doc(
			{
				"doctype": "Subscription",
				"team": self.team,
				"asset_id": self.asset,
				"plan": plan or self.plan,
				"enabled": 1,
			}
		).insert()

	def test_created_change_carries_subscription_and_plan(self):
		sub = self._make_subscription()
		change = frappe.get_doc(
			"Subscription Change",
			frappe.get_all(
				"Subscription Change",
				filters={"subscription": sub.name, "change_type": "Created"},
				pluck="name",
			)[0],
		)
		self.assertEqual(change.subscription, sub.name)
		self.assertEqual(change.new_value, self.plan)
		# team is fetched from the linked subscription.
		self.assertEqual(change.team, self.team)

	def test_history_is_append_only(self):
		sub = self._make_subscription()
		change = frappe.get_doc(
			"Subscription Change",
			frappe.get_all(
				"Subscription Change",
				filters={"subscription": sub.name, "change_type": "Created"},
				pluck="name",
			)[0],
		)
		change.new_value = "tampered"
		with self.assertRaises(frappe.ValidationError):
			change.save(ignore_permissions=True)

	def test_plan_update_appends_new_change_row_not_edit(self):
		sub = self._make_subscription()
		sub.plan = self.plan_b
		sub.save()

		all_changes = frappe.get_all("Subscription Change", filters={"subscription": sub.name}, pluck="change_type")
		self.assertEqual(sorted(all_changes), sorted(["Created", "Plan Changed"]))
