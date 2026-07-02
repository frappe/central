# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Admin dashboard endpoints (issue #19)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.api import admin
from central.billing.tests.utils import ensure_team, make_plan, seed_running_resource

PLAN = "bundle-admin-test"
TEAM_A = "team-admin-a"
TEAM_B = "team-admin-b"


class AdminTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM_A)
		ensure_team(TEAM_B)
		make_plan(PLAN)
		self._purge()

	def tearDown(self):
		frappe.set_user("Administrator")
		self._purge()

	def _purge(self):
		for team in (TEAM_A, TEAM_B):
			for dt in ("Invoice", "Payment Attempt", "Credit Ledger Entry"):
				frappe.db.delete(dt, {"team": team})
			frappe.db.delete("Credit Wallet", {"team": team})
			for sub in frappe.get_all("Subscription", {"team": team}, pluck="name"):
				frappe.db.delete("Subscription Change", {"subscription": sub})
				frappe.db.delete("Subscription", {"name": sub})
			frappe.db.delete("Asset", {"team": team})
		frappe.db.commit()

	def _invoice(self, team, total, status="Paid", itype="Billable", cluster="ap-south-1",
				 due_date=None, paid=None):
		return frappe.get_doc(
			{"doctype": "Invoice", "team": team, "invoice_type": itype, "status": status,
			 "period_start": "2099-01-01", "period_end": "2099-01-31", "currency": "INR",
			 "subtotal": total, "total": total, "amount_paid": paid if paid is not None else (total if status == "Paid" else 0),
			 "due_date": due_date,
			 "items": [{"resource_type": "bundle", "plan": PLAN, "cluster": cluster, "rate": total, "days": 30, "amount": total}]}
		).insert(ignore_permissions=True).name


class TestAdminGating(AdminTestBase):
	def test_non_admin_gets_403(self):
		user = f"adm-{frappe.generate_hash(6)}@example.com"
		frappe.get_doc({"doctype": "User", "email": user, "first_name": "X", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			admin.get_summary()


class TestAggregates(AdminTestBase):
	def test_summary_billed_collected_outstanding(self):
		self._invoice(TEAM_A, 1000, status="Paid")
		self._invoice(TEAM_B, 500, status="Open", paid=0)
		s = admin.get_summary("2099-01-01", "2099-01-31")
		self.assertEqual(s["total_billed"], 1500)
		self.assertEqual(s["total_collected"], 1000)
		self.assertEqual(s["outstanding"], 500)

	def test_cluster_and_team_breakdown(self):
		self._invoice(TEAM_A, 1000, cluster="ap-south-1")
		self._invoice(TEAM_B, 400, cluster="us-east-1")
		clusters = {r["cluster"]: r["amount"] for r in admin.get_cluster_breakdown("2099-01-01", "2099-01-31")}
		self.assertEqual(clusters["ap-south-1"], 1000)
		self.assertEqual(clusters["us-east-1"], 400)
		teams = {r["team"]: r["amount"] for r in admin.get_team_breakdown("2099-01-01", "2099-01-31")}
		self.assertEqual(teams[TEAM_A], 1000)

	def test_free_trial_subsidy_by_cluster_and_plan(self):
		self._invoice(TEAM_A, 800, itype="Cost Report", cluster="ap-south-1")
		out = admin.get_free_trial_costs("2099-01-01", "2099-01-31")
		self.assertEqual(out["total_subsidy"], 800)
		self.assertEqual(out["by_cluster"]["ap-south-1"], 800)
		self.assertEqual(out["by_plan"][PLAN], 800)


class TestPanels(AdminTestBase):
	def test_payment_analytics_success_rate_and_reasons(self):
		inv = self._invoice(TEAM_A, 100, status="Open", paid=0)
		for status, code in [("Captured", None), ("Captured", None), ("Failed", "card_declined")]:
			frappe.get_doc(
				{"doctype": "Payment Attempt", "team": TEAM_A, "invoice": inv, "gateway": None,
				 "amount": 100, "status": status, "failure_code": code,
				 "initiated_at": "2099-01-10 00:00:00"}
			).insert(ignore_permissions=True)
		out = admin.get_payment_analytics("2099-01-01", "2099-01-31")
		gw = out["by_gateway"]["unknown"]
		self.assertEqual(gw["total"], 3)
		self.assertAlmostEqual(gw["success_rate"], round(2 / 3, 3))
		self.assertEqual(out["failure_reasons"]["card_declined"], 1)
		frappe.db.delete("Payment Attempt", {"team": TEAM_A})

	def test_overdue_aging_buckets(self):
		self._invoice(TEAM_A, 1000, status="Overdue", due_date="2099-01-06", paid=0)  # ~9 days at 6-10
		buckets = admin.get_overdue_aging(now="2099-01-15")
		self.assertEqual(buckets["8-15"]["count"], 1)
		self.assertEqual(buckets["8-15"]["amount"], 1000)

	def test_team_lookup_returns_full_picture(self):
		self._invoice(TEAM_A, 1000)
		from central.billing.revenue import credits

		credits.purchase(TEAM_A, 250, "INR")
		out = admin.get_team_billing(TEAM_A)
		self.assertEqual(out["credit_balance"], 250)
		self.assertEqual(len(out["invoices"]), 1)


class TestPriceManagement(AdminTestBase):
	def test_update_rate_does_not_touch_existing_segments(self):
		# An existing running subscription with a grandfathered locked segment (ADR 0010).
		from central.billing.catalog.subscriptions import current_segment_rate

		sub = seed_running_resource(TEAM_A, "srv-x", "ap-south-1", PLAN, rate=3200, currency="INR")

		admin.update_plan_rate(PLAN, "INR", 5000)
		# The live catalog rate moved...
		self.assertEqual(frappe.get_doc("Plan", PLAN).get_rate("INR"), 5000)
		# ...but the running segment's locked rate is unchanged.
		self.assertEqual(current_segment_rate(sub), 3200)


class TestMetricsReports(AdminTestBase):
	def test_metrics_counts_and_mrr(self):
		from central.billing.catalog import subscriptions

		subscriptions.create_subscription(team=TEAM_A, cluster="ap-south-1", plan=PLAN, billing_cycle="Monthly")
		sub_b = subscriptions.create_subscription(team=TEAM_B, cluster="ap-south-1", plan=PLAN, billing_cycle="Monthly")
		subscriptions.set_standing(sub_b.name, "Past Due")

		m = admin.get_metrics()
		self.assertGreaterEqual(m["team_count"], 2)
		self.assertGreaterEqual(m["delinquent"], 1)
		self.assertGreater(m["mrr"], 0)
		self.assertIn("payment_failures", m)

		teams = {t["team"]: t for t in admin.list_teams()}
		self.assertEqual(teams[TEAM_B]["standing"], "Past Due")
		self.assertGreater(teams[TEAM_A]["mrr"], 0)
		for team in (TEAM_A, TEAM_B):
			for sub in frappe.get_all("Subscription", {"team": team}, pluck="name"):
				frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"team": team})
