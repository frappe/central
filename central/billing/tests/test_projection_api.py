# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The operator entry point onto projections."""

import frappe

from central.billing.api.admin import projection as api
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	ensure_team,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-projection-api"
CLUSTER = "ap-south-1"
PLAN = "bundle-projection-api"


class ProjectionApiTestBase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_team(TEAM)
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 9000, "2026-01-01 00:00:00")
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": TEAM})
		frappe.db.commit()


class TestGating(ProjectionApiTestBase):
	def test_a_non_operator_cannot_project_another_team(self):
		# A projection exposes somebody else's money, so it is operator-only rather than
		# team-scoped.
		user = f"proj-{frappe.generate_hash(6)}@example.com"
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "X", "send_welcome_email": 0}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()

		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			api.project_team(TEAM)

	def test_an_operator_gets_a_projection(self):
		out = api.project_team(TEAM, period_start="2026-09-01", period_end="2026-09-30")
		self.assertEqual(out["team"], TEAM)
		self.assertEqual(out["invoice"]["subtotal"], 9000.0)


class TestDefaults(ProjectionApiTestBase):
	def test_it_defaults_to_the_month_in_flight(self):
		out = api.project_team(TEAM, today="2026-09-15")
		self.assertEqual(out["period_start"], "2026-09-01")
		self.assertEqual(out["period_end"], "2026-09-30")
		self.assertEqual(out["as_of"], "2026-09-15")

	def test_an_explicit_period_wins(self):
		out = api.project_team(TEAM, period_start="2026-11-01", today="2026-09-15")
		self.assertEqual(out["period_start"], "2026-11-01")
		self.assertEqual(out["period_end"], "2026-11-30")

	def test_projecting_through_the_api_still_writes_nothing(self):
		before = frappe.db.count("Invoice", {"team": TEAM})
		api.project_team(TEAM, period_start="2026-09-01")
		self.assertEqual(frappe.db.count("Invoice", {"team": TEAM}), before)
