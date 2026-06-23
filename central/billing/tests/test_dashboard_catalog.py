# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Create-server plan menu: cluster availability + trust-tier spend filter."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.api.dashboard.catalog import get_eligible_plans
from central.billing.tests.utils import (
	clear_team_tier,
	complete_billing_profile,
	ensure_team,
	make_plan,
	set_team_tier,
)

TEAM = "team-srv-catalog"
CLUSTER = "ap-south-1"
OTHER_CLUSTER = "eu-central-1"

CHEAP = "bundle-cheap"      # 1000 INR
MID = "bundle-mid"          # 2000 INR
PRICEY = "bundle-pricey"    # 5000 INR
REGIONAL = "bundle-regional"  # priced only on CLUSTER


def _ensure_tier_level(name):
	"""A linkable Trust Tier Level so set_team_tier's pin resolves and the level's
	allow-lists are read. Money caps come from set_team_tier's override, so the
	threshold here is just a placeholder INR row."""
	if frappe.db.exists("Trust Tier Level", name):
		frappe.delete_doc("Trust Tier Level", name, force=True)
	frappe.get_doc(
		{
			"doctype": "Trust Tier Level", "__newname": name, "tier": name,
			"sequence": 1, "is_default": 0, "max_resource_count": 50, "min_paid_invoices": 0,
			"thresholds": [{"currency": "INR", "max_spend": 100000, "min_cumulative_paid": 0}],
		}
	).insert(ignore_permissions=True)


def _rates(global_inr, cluster=None, cluster_inr=None):
	rows = [{"cluster": "", "currency": "INR", "rate": global_inr}]
	if cluster:
		rows.append({"cluster": cluster, "currency": "INR", "rate": cluster_inr})
	return rows


class TestEligiblePlans(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		clear_team_tier(TEAM)  # each test pins (or leaves untiered) its own cap
		frappe.db.delete("Price Lock", {"team": TEAM})  # start with no committed usage
		_ensure_tier_level("t1")
		make_plan(CHEAP, rates=_rates(1000))
		make_plan(MID, rates=_rates(2000))
		make_plan(PRICEY, rates=_rates(5000))
		# Priced only on CLUSTER (no global INR row) → invisible elsewhere.
		make_plan(REGIONAL, rates=[{"cluster": CLUSTER, "currency": "INR", "rate": 1500}])
		frappe.set_user("Administrator")

	def _titles(self, cluster=CLUSTER):
		out = get_eligible_plans(cluster=cluster, team=TEAM)
		return {p["plan"] for p in out["plans"]}, out

	def _provision(self, plan, rate, cluster=CLUSTER):
		"""A running resource that consumes `rate` of the team's cap (active lock)."""
		frappe.get_doc(
			{
				"doctype": "Price Lock", "team": TEAM, "plan": plan, "cluster": cluster,
				"resource_id": f"srv-{frappe.generate_hash(6)}", "currency": "INR",
				"locked_rate": rate, "started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

	def test_spend_cap_hides_plans_above_the_ceiling(self):
		set_team_tier(TEAM, max_spend=2000)  # admits CHEAP (1000) + MID (2000), not PRICEY
		plans, out = self._titles()
		self.assertEqual(out["max_spend"], 2000)
		self.assertIn(CHEAP, plans)
		self.assertIn(MID, plans)
		self.assertNotIn(PRICEY, plans)

	def test_existing_usage_reduces_headroom(self):
		# 4000 cap, already running a 1000 server → 3000 headroom. MID (2000) fits,
		# PRICEY (5000) and any 3001+ plan do not.
		set_team_tier(TEAM, max_spend=4000)
		self._provision(CHEAP, 1000)
		plans, out = self._titles()
		self.assertEqual(out["max_spend"], 4000)
		self.assertEqual(out["current_spend"], 1000)
		self.assertEqual(out["available"], 3000)
		self.assertIn(MID, plans)
		self.assertNotIn(PRICEY, plans)

	def test_usage_at_cap_leaves_no_paid_headroom(self):
		set_team_tier(TEAM, max_spend=2000)
		self._provision(MID, 2000)  # consumes the whole cap
		plans, out = self._titles()
		self.assertEqual(out["available"], 0)
		self.assertEqual({CHEAP, MID, PRICEY} & plans, set())

	def test_higher_cap_reveals_more_plans(self):
		set_team_tier(TEAM, max_spend=6000)
		plans, _ = self._titles()
		self.assertTrue({CHEAP, MID, PRICEY, REGIONAL}.issubset(plans))

	def test_regional_plan_only_on_its_cluster(self):
		set_team_tier(TEAM, max_spend=6000)
		on_cluster, _ = self._titles(cluster=CLUSTER)
		off_cluster, _ = self._titles(cluster=OTHER_CLUSTER)
		self.assertIn(REGIONAL, on_cluster)
		self.assertNotIn(REGIONAL, off_cluster)

	def test_resolved_rate_is_the_cluster_rate(self):
		set_team_tier(TEAM, max_spend=6000)
		# Re-price CHEAP cheaper on CLUSTER; the menu must show the regional rate.
		make_plan(CHEAP, rates=_rates(1000, cluster=CLUSTER, cluster_inr=800))
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		row = next(p for p in out["plans"] if p["plan"] == CHEAP)
		self.assertEqual(row["rate"], 800)

	def test_allowed_plans_allowlist_restricts_menu(self):
		set_team_tier(TEAM, max_spend=6000)
		frappe.db.set_value("Trust Tier Level", "t1", "allowed_plans", frappe.as_json([CHEAP, MID]))
		self.addCleanup(frappe.db.set_value, "Trust Tier Level", "t1", "allowed_plans", None)
		plans, _ = self._titles()
		self.assertEqual(plans, {CHEAP, MID})

	def test_allowed_clusters_forbidden_cluster_yields_empty(self):
		set_team_tier(TEAM, max_spend=6000)
		frappe.db.set_value("Trust Tier Level", "t1", "allowed_clusters", frappe.as_json([OTHER_CLUSTER]))
		self.addCleanup(frappe.db.set_value, "Trust Tier Level", "t1", "allowed_clusters", None)
		plans, out = self._titles(cluster=CLUSTER)
		self.assertEqual(plans, set())

	def test_untiered_team_has_no_headroom(self):
		# No tier pinned → 0 cap → no paid plan fits (only free plans, if any).
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["max_spend"], 0)
		self.assertTrue(all(p["rate"] == 0 for p in out["plans"]))
		self.assertEqual({CHEAP, MID, PRICEY} & {p["plan"] for p in out["plans"]}, set())

	def test_inactive_plan_is_excluded(self):
		set_team_tier(TEAM, max_spend=6000)
		make_plan(MID, rates=_rates(2000), is_active=0)
		plans, _ = self._titles()
		self.assertNotIn(MID, plans)
