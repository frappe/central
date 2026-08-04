# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""get_eligible_plans returns the rate card + profile bounds + headroom; provision
re-validates composition, bounds, and headroom server-side (#83)."""

import frappe

from central.billing.api.dashboard.catalog import (
	get_composed_config,
	get_eligible_plans,
	provision_composed_config,
	resize_composed_config,
	resize_server,
)
from central.billing.catalog.pricing import set_catalog_rate
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	run_enqueued_inline,
	set_team_tier,
)

TEAM = "team-eligible-composed"
CLUSTER = "ap-south-1"
OTHER = "eu-central-1"
GENERAL = [
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
]  # 2*500 + 8*250 + 40*10 = 3400


class TestEligibilityComposed(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")  # a prior test may have left a customer user
		ensure_atlas_instance(CLUSTER)
		ensure_atlas_instance(OTHER)
		# This suite covers the composed rate card / bounds, not live capacity — keep the
		# capacity gate off so get_eligible_plans doesn't reach for the region's Atlas
		# (its own coverage lives in test_capacity_filter.py).
		frappe.db.set_value("Atlas Instance", CLUSTER, "validate_capacity", 0)
		frappe.db.set_value("Atlas Instance", OTHER, "validate_capacity", 0)
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		set_team_tier(TEAM, max_spend=100000)
		# Baseline: a global-only INR component card (drop any regional row a prior
		# test left behind, since this site doesn't roll back between tests).
		for name in frappe.get_all(
			"Catalog Rate", filters={"priced_doctype": "Resource Type", "cluster": ["!=", ""]}, pluck="name"
		):
			frappe.delete_doc("Catalog Rate", name, force=True)
		for resource_type, rate in (("Compute", 500), ("Memory", 250), ("Disk", 10)):
			set_catalog_rate("Resource Type", resource_type, "INR", rate)
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		frappe.set_user("Administrator")

	def test_returns_rate_card_profiles_available(self):
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["rate_card"]["Compute"], {"rate": 500, "unit": "vCPU"})
		self.assertEqual(out["rate_card"]["Memory"], {"rate": 250, "unit": "GB"})
		self.assertEqual(out["rate_card"]["Disk"], {"rate": 10, "unit": "GB"})
		general = next(p for p in out["profiles"] if p["sub_category"] == "General")
		self.assertEqual(general["ram_ratio"], 4)
		# The configurator ladder: fractional vCPUs through powers of two.
		self.assertEqual(general["vcpu_steps"][:5], [0.125, 0.25, 0.5, 1, 2])
		# Storage ladder rungs within [disk_min, disk_max] (10..2000).
		self.assertEqual(general["disk_steps"], [10, 20, 50, 100, 200, 500, 1000, 2000])
		self.assertEqual(general["disk_min"], 10)
		self.assertEqual(general["disk_max"], 2000)
		self.assertEqual(out["available"], out["max_spend"])  # no usage yet

	def test_rate_card_regional_over_global(self):
		set_catalog_rate("Resource Type", "Compute", "INR", 550, cluster=CLUSTER)
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["rate_card"]["Compute"]["rate"], 550)
		# A different cluster falls back to the global rate.
		self.assertEqual(get_eligible_plans(cluster=OTHER, team=TEAM)["rate_card"]["Compute"]["rate"], 500)

	def test_currency_without_component_rates_has_no_rate_card(self):
		complete_billing_profile(TEAM, currency="JPY")  # no JPY component rates seeded
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["rate_card"], {})  # composed configs not offered, not zeros

	def test_region_not_allowed_empties_presets_and_rate_card(self):
		frappe.db.set_value("Trust Tier Level", "t1", "allowed_clusters", frappe.as_json([OTHER]))
		self.addCleanup(frappe.db.set_value, "Trust Tier Level", "t1", "allowed_clusters", None)
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["plans"], {})
		self.assertEqual(out["rate_card"], {})
		self.assertEqual(out["profiles"], [])

	def test_run_rate_counts_a_composed_config(self):
		from central.billing.catalog import subscriptions

		provisioned = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		frappe.db.set_value("Subscription", provisioned["subscription"], "enabled", 1)
		out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["current_spend"], 3400)
		self.assertEqual(out["available"], out["max_spend"] - 3400)

	def test_provision_just_over_headroom_refused(self):
		set_team_tier(TEAM, max_spend=3000)  # below the 3400 config
		with self.assertRaises(frappe.ValidationError):
			provision_composed_config(GENERAL, "General", CLUSTER, team=TEAM)

	def test_provision_just_under_headroom_succeeds(self):
		set_team_tier(TEAM, max_spend=3400)  # exactly covers the config
		out = provision_composed_config(GENERAL, "General", CLUSTER, team=TEAM)
		self.assertEqual(out["locked_rate"], 3400)

	def test_provision_off_ratio_refused_serverside(self):
		bad = [
			{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
			{"resource_type": "Memory", "quantity": 4, "unit": "GB"},  # General needs 8
			{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
		]
		with self.assertRaises(frappe.ValidationError):
			provision_composed_config(bad, "General", CLUSTER, team=TEAM)

	def test_get_composed_config_returns_shape_and_resize_headroom(self):
		from central.billing.catalog import subscriptions

		out = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		got = get_composed_config(out["resource_id"], team=TEAM)
		self.assertTrue(got["composed"])
		self.assertEqual(got["subscription"], out["subscription"])
		self.assertEqual((got["vcpus"], got["memory_gb"], got["disk_gb"]), (2, 8, 40))
		# Resize headroom excludes this config's own spend, so it has the full cap back.
		self.assertEqual(
			got["available"],
			frappe.utils.flt(get_eligible_plans(cluster=CLUSTER, team=TEAM)["max_spend"]),
		)

	def test_get_composed_config_preset_returns_vm_shape_for_resize(self):
		from central.billing.catalog import subscriptions
		from central.billing.tests.utils import make_plan

		plan = make_plan("preset-for-config", rates=[{"cluster": "", "currency": "INR", "rate": 1000}])
		sub = subscriptions.create_subscription(TEAM, CLUSTER, plan=plan)
		# A preset carries its shape on the mirrored VM (Atlas fills these on vm.created).
		frappe.db.set_value(
			"Asset", sub.asset_id, {"vcpus": 2, "memory_megabytes": 4096, "disk_gigabytes": 25}
		)
		got = get_composed_config(sub.asset_id, team=TEAM)
		self.assertTrue(got["resizable"])
		self.assertFalse(got["composed"])  # sliding it will make it composed
		self.assertIsNone(got["sub_category"])  # designer defaults to the first profile
		self.assertEqual((got["vcpus"], got["memory_gb"], got["disk_gb"]), (2, 4, 25))

	def test_resize_endpoint_relocks(self):
		from unittest.mock import patch

		from central.billing.catalog import subscriptions

		out = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		# A resize needs a Stopped VM and drives the real machine on its Atlas; mark it
		# stopped and stub the outbound call so this stays an endpoint-logic test.
		frappe.db.set_value("Asset", out["resource_id"], "status", "Stopped")
		bigger = [
			{"resource_type": "Compute", "quantity": 4, "unit": "vCPU"},
			{"resource_type": "Memory", "quantity": 16, "unit": "GB"},
			{"resource_type": "Disk", "quantity": 40, "unit": "GB"},
		]
		with (
			patch("central.integrations.atlas.AtlasClient.resize_vm", return_value="task-1"),
			patch("central.integrations.atlas.AtlasClient.vm_action", return_value="task-2"),
		):
			result = resize_composed_config(out["subscription"], bigger, "General")
		self.assertTrue(result["resized"])
		self.assertEqual(
			frappe.db.count(
				"Subscription Change", {"subscription": out["subscription"], "change_type": "Plan Changed"}
			),
			1,
		)

	def test_resize_server_onto_preset_bundle(self):
		from unittest.mock import patch

		from central.billing.catalog import subscriptions
		from central.billing.tests.utils import make_plan

		out = subscriptions.provision_composed_subscription(TEAM, CLUSTER, GENERAL, "General")
		frappe.db.set_value("Asset", out["resource_id"], "status", "Stopped")
		plan = make_plan("resize-bundle", rates=[{"cluster": "", "currency": "INR", "rate": 1500}])
		# The reshape + re-lock are deferred to a background job; run it inline here to
		# assert the end-to-end effect (queued path).
		with (
			patch("central.integrations.atlas.AtlasClient.resize_vm", return_value="task-1") as resize_vm,
			patch("central.integrations.atlas.AtlasClient.vm_action", return_value="task-2"),
			patch("frappe.enqueue", side_effect=run_enqueued_inline),
		):
			result = resize_server(out["subscription"], plan=plan)
		self.assertTrue(result["resized"])
		self.assertTrue(result["queued"])  # a live VM was reshaped in the background
		resize_vm.assert_called_once()  # the bundle's shape drove a real VM resize
		doc = frappe.get_doc("Subscription", out["subscription"])
		self.assertEqual((doc.pricing_mode, doc.plan), ("Preset", plan))
		# The Resizing flag is set for the job and cleared when it finishes.
		self.assertEqual(frappe.db.get_value("Asset", out["resource_id"], "resize_in_progress"), 0)
