# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe

from central.billing.catalog import subscriptions
from central.billing.revenue import invoicing
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	clear_team_tier,
	make_billing_subscription,
	make_plan,
	set_team_tier,
)

TEAM = "team-pause-billing"
CLUSTER = "ap-south-1"
PLAN = "bundle-pause-billing"


class PauseBillingTestBase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		self.subscription = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		self.server = frappe.db.get_value("Subscription", self.subscription, "server_id")
		# Pause and resume drive the server through Atlas; the billing effect is what is under test.
		self.enterContext(patch.object(subscriptions, "_control_subscription_server"))
		self.addCleanup(self._purge)

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Project", {"team": TEAM})
		for name in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.db.delete("Subscription", {"name": name})
		frappe.db.commit()

	def _invoice_lines(self) -> list:
		name = invoicing.generate_draft_invoice(self.subscription, "2026-06-01", "2026-06-30")
		return frappe.get_doc("Invoice", name).items

	def _changes(self, subscription: str) -> list:
		return frappe.get_all(
			"Subscription Change",
			filters={"subscription": subscription},
			fields=["change_type", "locked_rate", "new_value"],
			order_by="effective_at asc, creation asc",
		)


class TestPausedServerRating(PauseBillingTestBase):
	def test_a_paused_server_bills_nothing_after_the_pause(self):
		add_segment(self.subscription, "Created", 3000, "2026-06-01 00:00:00", plan=PLAN)
		add_segment(self.subscription, "Paused", None, "2026-06-11 00:00:00")

		lines = self._invoice_lines()

		self.assertEqual([(line.unit, line.days) for line in lines], [("day", 10)])
		self.assertEqual(sum(line.amount for line in lines), 1000.0)

	def test_a_pause_mid_day_bills_the_hours_before_it(self):
		add_segment(self.subscription, "Created", 3000, "2026-06-01 00:00:00", plan=PLAN)
		add_segment(self.subscription, "Paused", None, "2026-06-11 06:00:00")

		lines = self._invoice_lines()

		self.assertEqual(
			sorted((line.unit, line.days or line.hours) for line in lines), [("day", 10), ("hour", 6.0)]
		)

	def test_a_resumed_server_bills_again_from_the_resume(self):
		add_segment(self.subscription, "Created", 3000, "2026-06-01 00:00:00", plan=PLAN)
		add_segment(self.subscription, "Paused", None, "2026-06-11 00:00:00")
		add_segment(self.subscription, "Resumed", 3000, "2026-06-21 00:00:00", plan=PLAN)

		lines = self._invoice_lines()

		self.assertEqual(sorted(line.days for line in lines), [10, 10])
		self.assertEqual(sum(line.amount for line in lines), 2000.0)


class TestPauseAndResume(PauseBillingTestBase):
	def setUp(self):
		super().setUp()
		add_segment(self.subscription, "Created", 3000, "2026-06-01 00:00:00", plan=PLAN)
		frappe.db.set_value("Subscription", self.subscription, "enabled", 1)
		set_team_tier(TEAM, max_spend=100000)
		self.addCleanup(clear_team_tier, TEAM)

	def test_resume_reopens_at_the_rate_locked_before_the_pause(self):
		subscriptions.pause_billing(self.subscription)
		subscriptions.resume_billing(self.subscription)

		resumed = self._changes(self.subscription)[-1]
		self.assertEqual(
			(resumed.change_type, resumed.locked_rate, resumed.new_value), ("Resumed", 3000, PLAN)
		)

	def test_a_paused_server_is_not_running(self):
		subscriptions.pause_billing(self.subscription)

		self.assertEqual(subscriptions.current_segment_rate(self.subscription), 0.0)
		self.assertFalse(subscriptions.active_segments({"name": self.subscription}))

	def test_pause_and_resume_carry_the_servers_public_ipv4(self):
		address = self._public_ipv4_subscription()

		subscriptions.pause_billing(self.subscription)
		self.assertEqual(self._changes(address)[-1].change_type, "Paused")

		subscriptions.resume_billing(self.subscription)
		resumed = self._changes(address)[-1]
		self.assertEqual((resumed.change_type, resumed.locked_rate), ("Resumed", 170))

	def test_resume_over_the_spending_limit_is_refused(self):
		subscriptions.pause_billing(self.subscription)
		set_team_tier(TEAM, max_spend=1000)

		with self.assertRaises(frappe.ValidationError):
			subscriptions.resume_billing(self.subscription)
		self.assertEqual(self._changes(self.subscription)[-1].change_type, "Paused")

	def test_pausing_a_subscription_with_no_server_is_refused(self):
		frappe.db.set_value("Subscription", self.subscription, "server_id", None)

		with self.assertRaises(frappe.ValidationError):
			subscriptions.pause_billing(self.subscription)

	def test_resuming_a_cancelled_subscription_is_refused(self):
		subscriptions.cancel_subscription(self.subscription)

		with self.assertRaises(frappe.ValidationError):
			subscriptions.resume_billing(self.subscription)

	def test_the_project_limit_on_resume_leaves_out_the_public_ipv4(self):
		self._public_ipv4_subscription()
		project = frappe.get_doc(
			{"doctype": "Project", "title": "Paused", "team": TEAM, "spending_limit": 3000}
		).insert()
		frappe.db.set_value("Subscription", self.subscription, "project", project.name)
		subscriptions.pause_billing(self.subscription)

		subscriptions.resume_billing(self.subscription)

		self.assertEqual(subscriptions.current_segment_rate(self.subscription), 3000)

	def test_terminating_a_paused_server_cancels_its_subscription(self):
		subscriptions.pause_billing(self.subscription)

		frappe.get_doc("Virtual Machine", self.server).disable_active_subscription()

		self.assertEqual(self._changes(self.subscription)[-1].change_type, "Cancelled")

	def _public_ipv4_subscription(self) -> str:
		address = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		frappe.db.set_value(
			"Subscription", address, {"server_id": None, "public_ip_server": self.server, "enabled": 1}
		)
		add_segment(address, "Created", 170, "2026-06-01 00:00:00", plan=PLAN)
		return address
