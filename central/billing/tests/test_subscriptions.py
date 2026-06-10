# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Subscription intent + two-axis state model (issue #04)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import subscriptions
from central.billing.catalog.subscriptions import InvalidTransition
from central.billing.tests.utils import ensure_team, make_plan

PLAN = "bundle-sub-test"
PLAN_B = "bundle-sub-test-b"
TEAM = "team-sub"


def changes_for(sub, change_type=None):
	filters = {"subscription": sub}
	if change_type:
		filters["change_type"] = change_type
	return frappe.get_all("Subscription Change", filters=filters, pluck="name")


class SubscriptionTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_plan(PLAN)
		make_plan(PLAN_B)
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			for c in changes_for(name):
				frappe.delete_doc("Subscription Change", c, force=True)
			frappe.delete_doc("Subscription", name, force=True)

	def make_sub(self):
		return subscriptions.create_subscription(
			team=TEAM, cluster="ap-south-1", plan=PLAN, billing_cycle="monthly"
		)


class TestSubscriptionIntent(SubscriptionTestBase):
	def test_create_records_intent_and_writes_created_change(self):
		sub = self.make_sub()
		self.assertEqual(sub.account_standing, "current")  # starts in good standing
		self.assertEqual(sub.plan, PLAN)
		self.assertEqual(len(changes_for(sub.name, "created")), 1)

	def test_no_combined_operational_financial_enum_exists(self):
		# Central owns ONLY account_standing; operational state is the Agent's.
		meta = frappe.get_meta("Subscription")
		standing = meta.get_field("account_standing")
		self.assertEqual(
			sorted(o for o in standing.options.split("\n") if o),
			["current", "past_due", "suspended"],
		)
		# No field carries the operational axis.
		fieldnames = {df.fieldname for df in meta.fields}
		self.assertNotIn("operational_state", fieldnames)
		self.assertFalse(any("running" in (df.options or "") for df in meta.fields))

	def test_change_plan_writes_history(self):
		sub = self.make_sub()
		subscriptions.change_plan(sub.name, PLAN_B)
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "plan"), PLAN_B)
		change = frappe.get_doc("Subscription Change", changes_for(sub.name, "plan_changed")[0])
		self.assertEqual(change.old_value, PLAN)
		self.assertEqual(change.new_value, PLAN_B)

	def test_cancel_writes_history(self):
		sub = self.make_sub()
		subscriptions.cancel_subscription(sub.name)
		self.assertEqual(len(changes_for(sub.name, "cancelled")), 1)

	def test_history_is_append_only(self):
		sub = self.make_sub()
		change = frappe.get_doc("Subscription Change", changes_for(sub.name, "created")[0])
		change.new_value = "tampered"
		with self.assertRaises(frappe.ValidationError):
			change.save(ignore_permissions=True)


class TestAccountStandingStateMachine(SubscriptionTestBase):
	def test_grace_then_suspend_then_reactivate(self):
		sub = self.make_sub()
		subscriptions.set_standing(sub.name, "past_due")
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "account_standing"), "past_due")
		subscriptions.set_standing(sub.name, "suspended")
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "account_standing"), "suspended")
		subscriptions.set_standing(sub.name, "current")
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "account_standing"), "current")
		# Each transition is logged.
		self.assertTrue(changes_for(sub.name, "past_due"))
		self.assertTrue(changes_for(sub.name, "suspended"))
		self.assertTrue(changes_for(sub.name, "reactivated"))

	def test_past_due_can_recover_directly_to_current(self):
		sub = self.make_sub()
		subscriptions.set_standing(sub.name, "past_due")
		subscriptions.set_standing(sub.name, "current")
		self.assertEqual(frappe.db.get_value("Subscription", sub.name, "account_standing"), "current")

	def test_invalid_transitions_raise(self):
		sub = self.make_sub()
		# current -> suspended skips the grace step.
		with self.assertRaises(InvalidTransition):
			subscriptions.set_standing(sub.name, "suspended")
		# current -> current is a no-op transition, not allowed.
		with self.assertRaises(InvalidTransition):
			subscriptions.set_standing(sub.name, "current")
		# Move to past_due, then an illegal jump back-and-forth.
		subscriptions.set_standing(sub.name, "past_due")
		with self.assertRaises(InvalidTransition):
			subscriptions.set_standing(sub.name, "past_due")  # same-state

	def test_unknown_standing_raises(self):
		sub = self.make_sub()
		with self.assertRaises(InvalidTransition):
			subscriptions.set_standing(sub.name, "deleted")


class TestReconciliation(SubscriptionTestBase):
	def test_reconcile_flags_missing_cluster_event(self):
		sub = self.make_sub()
		result = subscriptions.reconcile_with_agent_event(sub.name, "srv-unknown")
		self.assertFalse(result["reconciled"])
		self.assertEqual(result["reason"], "no_cluster_event")

	def test_reconcile_matches_locked_plan(self):
		from central.billing.platform.sync import receive_usage_events

		sub = self.make_sub()
		# Agent reports the resource for this plan → Central locks it.
		receive_usage_events(
			[
				{
					"event_id": "evt-sub-1",
					"team": TEAM,
					"resource_id": "srv-sub-1",
					"cluster": "ap-south-1",
					"plan": PLAN,
					"shown_rate": 40,
					"currency": "USD",
					"event_type": "subscribed",
					"effective_from": str(frappe.utils.now_datetime()),
					"effective_to": None,
				}
			]
		)
		result = subscriptions.reconcile_with_agent_event(sub.name, "srv-sub-1")
		self.assertTrue(result["reconciled"])
		self.assertEqual(result["locked_plan"], PLAN)
