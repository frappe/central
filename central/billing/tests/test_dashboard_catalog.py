# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Create-server plan menu: cluster availability + trust-tier spend filter."""

import frappe

from central.billing.api.dashboard.catalog import get_eligible_plans
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	clear_team_tier,
	complete_billing_profile,
	ensure_team,
	make_metered_plan,
	make_plan,
	set_team_tier,
)

TEAM = "team-srv-catalog"
CLUSTER = "ap-south-1"
OTHER_CLUSTER = "eu-central-1"

CHEAP = "bundle-cheap"  # 1000 INR
MID = "bundle-mid"  # 2000 INR
PRICEY = "bundle-pricey"  # 5000 INR
REGIONAL = "bundle-regional"  # priced only on CLUSTER


def _ensure_tier_level(name):
	"""A linkable Trust Tier Level so set_team_tier's pin resolves and the level's
	allow-lists are read. Money caps come from set_team_tier's override, so the
	threshold here is just a placeholder INR row."""
	if frappe.db.exists("Trust Tier Level", name):
		frappe.delete_doc("Trust Tier Level", name, force=True)
	frappe.get_doc(
		{
			"doctype": "Trust Tier Level",
			"__newname": name,
			"tier": name,
			"sequence": 1,
			"is_default": 0,
			"max_resource_count": 50,
			"min_paid_invoices": 0,
			"thresholds": [{"currency": "INR", "max_spend": 100000, "min_cumulative_paid": 0}],
		}
	).insert(ignore_permissions=True)


def _rates(global_inr, cluster=None, cluster_inr=None):
	rows = [{"cluster": "", "currency": "INR", "rate": global_inr}]
	if cluster:
		rows.append({"cluster": cluster, "currency": "INR", "rate": cluster_inr})
	return rows


def _flat(out):
	"""All plan rows across the grouped `{sub_category: [rows]}` menu."""
	return [p for rows in out["plans"].values() for p in rows]


class TestEligiblePlans(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		clear_team_tier(TEAM)  # each test pins (or leaves untiered) its own cap
		# Start with no committed usage: drop the team's subscriptions (the run-rate is
		# summed off their Subscription Change ledger now, ADR 0010).
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		_ensure_tier_level("t1")
		make_plan(CHEAP, rates=_rates(1000))
		make_plan(MID, rates=_rates(2000))
		make_plan(PRICEY, rates=_rates(5000))
		# Priced only on CLUSTER (no global INR row) → invisible elsewhere.
		make_plan(REGIONAL, rates=[{"cluster": CLUSTER, "currency": "INR", "rate": 1500}])
		# These tests exercise the tier/currency filter, not live capacity — the pricing
		# above created the CLUSTER Atlas Instance (validate_capacity on by default); turn
		# it off so get_eligible_plans doesn't reach for the region's capacity API.
		# The capacity gate has its own suite (test_capacity_filter.py).
		frappe.db.set_value("Atlas Instance", CLUSTER, "validate_capacity", 0)
		frappe.set_user("Administrator")

	def _titles(self, cluster=CLUSTER):
		out = get_eligible_plans(cluster=cluster, team=TEAM)
		return {p["plan"] for p in _flat(out)}, out

	def _provision(self, plan, rate, cluster=CLUSTER):
		"""A running subscription that consumes the plan's rate of the team's cap (its
		opening Created segment on the ledger)."""
		from central.billing.catalog import subscriptions

		subscriptions.create_subscription(TEAM, cluster, plan=plan)

	def test_excludes_non_server_families(self):
		# An AI Tokens plan is billable but not provisioned via the create-server flow;
		# its family's provision_target is blank, so it never appears in the menu. AI
		# Tokens is Metered, so clear any leftover metered Tokens plan first (one per
		# resource type).
		_clear_metered_plans("Tokens")
		make_plan(
			"tokens-100m",
			category="AI Tokens",
			includes=[{"resource_type": "Tokens", "quantity": 100, "unit": "Nos"}],
			rates=_rates(800),
		)
		set_team_tier(TEAM, max_spend=100000)  # ample headroom — exclusion is by family, not price
		plans, _ = self._titles()
		self.assertIn(CHEAP, plans)  # a VM Plans (Server) family member shows
		self.assertNotIn("tokens-100m", plans)  # the AI Tokens family does not

	def test_excludes_metered_plans(self):
		# A metered single-resource plan (a former Add-on) is billed through metering,
		# not provisioned via create-server. Its family carries no provision_target, so
		# it must never surface in the menu (ADR 0008).
		make_metered_plan(
			"meter-menu-transfer",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 1}],
		)
		set_team_tier(TEAM, max_spend=100000)  # ample headroom — exclusion is by family
		plans, _ = self._titles()
		self.assertIn(CHEAP, plans)  # a VM Plans (Server) member shows
		self.assertNotIn("meter-menu-transfer", plans)  # the metered plan does not

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

	def test_plans_are_ordered_cheapest_first(self):
		set_team_tier(TEAM, max_spend=6000)
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		for rows in out["plans"].values():
			rates = [p["rate"] for p in rows]
			self.assertEqual(rates, sorted(rates))

	def test_plans_are_grouped_by_sub_category(self):
		set_team_tier(TEAM, max_spend=6000)
		# Re-classify two plans into VM Plans sub-categories; the rest stay unset →
		# folded into "General". The sub-categories are seeded by the taxonomy.
		frappe.db.set_value("Plan", MID, "sub_category", "CPU Optimised")
		frappe.db.set_value("Plan", PRICEY, "sub_category", "Memory Optimised")
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		# Keys come in canonical order, whatever subset of sub-categories the catalog has
		# (other suites seed plans of their own — don't assume a closed world).
		canonical = ["General", "CPU Optimised", "Memory Optimised", "Storage Optimised", "Custom"]
		keys = list(out["plans"])
		self.assertEqual(keys, [c for c in canonical if c in keys])
		# Each plan lands in its own sub-category; an unset sub-category stays General.
		self.assertIn(CHEAP, {p["plan"] for p in out["plans"]["General"]})
		self.assertIn(MID, {p["plan"] for p in out["plans"]["CPU Optimised"]})
		self.assertIn(PRICEY, {p["plan"] for p in out["plans"]["Memory Optimised"]})

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
		row = next(p for p in _flat(out) if p["plan"] == CHEAP)
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
		plans, _out = self._titles(cluster=CLUSTER)
		self.assertEqual(plans, set())

	def test_untiered_team_has_no_headroom(self):
		# No tier pinned → 0 cap → no paid plan fits (only free plans, if any).
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["max_spend"], 0)
		plans = _flat(out)
		self.assertTrue(all(p["rate"] == 0 for p in plans))
		self.assertEqual({CHEAP, MID, PRICEY} & {p["plan"] for p in plans}, set())

	def test_inactive_plan_is_excluded(self):
		set_team_tier(TEAM, max_spend=6000)
		make_plan(MID, rates=_rates(2000), is_active=0)
		plans, _ = self._titles()
		self.assertNotIn(MID, plans)


class TestTrialPlanMenu(IntegrationTestCase):
	"""A staging trial team's create-server menu: narrowed to the configured entry plans
	(`trial_plans`), design-your-own suppressed, and — crucially — NOT gated by the
	trust-tier spend cap. The team here is deliberately untiered (0 headroom), the state
	that hid every plan before the fix; a trial's spend is bounded by credits + the
	server cap, not the tier."""

	def setUp(self):
		ensure_team(TEAM)
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 1)
		self.addCleanup(frappe.db.set_value, "Team", TEAM, "is_staging_trial", 0)
		complete_billing_profile(TEAM, currency="INR")
		clear_team_tier(TEAM)  # untiered → 0 headroom; trials must still see plans
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		make_plan(CHEAP, rates=_rates(1000))
		make_plan(MID, rates=_rates(2000))
		make_plan(PRICEY, rates=_rates(5000))
		frappe.db.set_value("Atlas Instance", CLUSTER, "validate_capacity", 0)
		frappe.set_user("Administrator")

	def test_untiered_trial_sees_plans_despite_zero_headroom(self):
		from unittest.mock import patch

		with patch.dict(frappe.conf, {"trial_plans": []}):  # no narrowing
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["available"], 0)  # untiered: the tier cap would hide everything
		plans = {p["plan"] for p in _flat(out)}
		self.assertTrue({CHEAP, MID, PRICEY}.issubset(plans))  # trial bypasses the headroom filter
		self.assertEqual(out["profiles"], [])  # composed still suppressed for a trial

	def test_menu_limited_to_configured_trial_plans(self):
		from unittest.mock import patch

		with patch.dict(frappe.conf, {"trial_plans": [CHEAP, MID]}):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		plans = {p["plan"] for p in _flat(out)}
		self.assertEqual(plans, {CHEAP, MID})  # PRICEY excluded by the allow-list
		self.assertEqual(out["profiles"], [])  # no design-your-own for a trial
		self.assertEqual(out["rate_card"], {})

	def test_non_trial_untiered_team_still_sees_nothing(self):
		# The bypass is trial-only: a normal untiered team is still headroom-gated to empty.
		frappe.db.set_value("Team", TEAM, "is_staging_trial", 0)
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual({CHEAP, MID, PRICEY} & {p["plan"] for p in _flat(out)}, set())
