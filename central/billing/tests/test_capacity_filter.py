# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Create/resize plan menu: the live-capacity gate (Atlas Instance.validate_capacity).

get_eligible_plans hides plans whose compute shape won't fit the largest VM the
region's Atlas can seat right now. The Atlas capacity call is mocked here — this
suite proves the gate's wiring (fit compare, no-room → empty, flag off / unreachable
→ show everything), not Atlas's own accounting."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.api.dashboard.catalog import get_eligible_plans
from central.billing.tests.utils import (
	clear_team_tier,
	complete_billing_profile,
	ensure_atlas_instance,
	ensure_team,
	make_plan,
	set_team_tier,
)
from central.integrations.atlas import AtlasClient

TEAM = "team-capacity-filter"
CLUSTER = "ap-south-1"

SMALL = "cap-small"  # 1 vCPU / 2 GB / 20 GB
BIG = "cap-big"      # 8 vCPU / 32 GB / 500 GB


def _shape(vcpu, memory_gb, disk_gb):
	return [
		{"resource_type": "Compute", "quantity": vcpu, "unit": "vCPU"},
		{"resource_type": "Memory", "quantity": memory_gb, "unit": "GB"},
		{"resource_type": "Disk", "quantity": disk_gb, "unit": "GB"},
	]


def _ensure_tier_level(name):
	if frappe.db.exists("Trust Tier Level", name):
		frappe.delete_doc("Trust Tier Level", name, force=True)
	frappe.get_doc(
		{
			"doctype": "Trust Tier Level", "__newname": name, "tier": name,
			"sequence": 1, "is_default": 0, "max_resource_count": 50, "min_paid_invoices": 0,
			"thresholds": [{"currency": "INR", "max_spend": 100000, "min_cumulative_paid": 0}],
		}
	).insert(ignore_permissions=True)


def _titles(out):
	return {p["plan"] for rows in out["plans"].values() for p in rows}


class TestCapacityFilter(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_team(TEAM)
		complete_billing_profile(TEAM, currency="INR")
		clear_team_tier(TEAM)
		for name in frappe.get_all("Subscription", filters={"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": name})
			frappe.delete_doc("Subscription", name, force=True)
		_ensure_tier_level("t1")
		set_team_tier(TEAM, max_spend=100000)  # ample headroom — the gate under test is capacity
		make_plan(SMALL, rates=[{"cluster": "", "currency": "INR", "rate": 1000}], includes=_shape(1, 2, 20))
		make_plan(BIG, rates=[{"cluster": "", "currency": "INR", "rate": 2000}], includes=_shape(8, 32, 500))
		ensure_atlas_instance(CLUSTER)
		frappe.db.set_value("Atlas Instance", CLUSTER, "validate_capacity", 1)
		frappe.set_user("Administrator")

	def _capacity(self, vcpus, memory_mb, disk_gb, available=True):
		return {
			"available": available,
			"unmeasured": False,
			"largest_vm": {"vcpus": vcpus, "memory_megabytes": memory_mb, "disk_gigabytes": disk_gb},
		}

	def test_hides_plans_that_dont_fit_the_region(self):
		# The region's best host can seat 4 vCPU / 8 GB / 200 GB: SMALL fits, BIG doesn't.
		cap = self._capacity(4, 8 * 1024, 200)
		with patch.object(AtlasClient, "capacity", return_value=cap):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		plans = _titles(out)
		self.assertIn(SMALL, plans)
		self.assertNotIn(BIG, plans)

	def test_fitting_plans_all_show(self):
		# Roomy host — everything fits.
		cap = self._capacity(16, 64 * 1024, 1000)
		with patch.object(AtlasClient, "capacity", return_value=cap):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		plans = _titles(out)
		self.assertIn(SMALL, plans)
		self.assertIn(BIG, plans)

	def test_memory_axis_is_scaled_to_mb(self):
		# 3 GB free would swallow BIG's 32 GB if the axis were compared in GB by mistake.
		cap = self._capacity(16, 3, 1000)  # 3 MB of RAM — nothing fits
		with patch.object(AtlasClient, "capacity", return_value=cap):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(_titles(out), set())

	def test_no_room_yields_empty_menu(self):
		# largest_vm None → no Active host with room → the whole menu is empty, composed
		# configs included (rate card / profiles come back empty too). The capacity block
		# tells the client to show a "region is full" message.
		nothing = {"available": False, "unmeasured": False, "largest_vm": None}
		with patch.object(AtlasClient, "capacity", return_value=nothing):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["plans"], {})
		self.assertEqual(out["rate_card"], {})
		self.assertEqual(out["profiles"], [])
		self.assertEqual(out["capacity"], {"gated": True, "available": False, "unmeasured": False, "largest_vm": None})

	def test_smallest_preset_not_fitting_yields_empty_menu(self):
		# `available` False even with a (tiny) largest_vm — Atlas says nothing provisions
		# here — is the same dead end: empty menu, region-full signal.
		full = self._capacity(1, 512, 5, available=False)
		with patch.object(AtlasClient, "capacity", return_value=full):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(out["plans"], {})
		self.assertEqual(out["rate_card"], {})
		self.assertFalse(out["capacity"]["available"])

	def test_capacity_block_reports_the_ceiling(self):
		cap = self._capacity(4, 8 * 1024, 200)
		with patch.object(AtlasClient, "capacity", return_value=cap):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		self.assertEqual(
			out["capacity"],
			{"gated": True, "available": True, "unmeasured": False,
			 "largest_vm": {"vcpus": 4, "memory_megabytes": 8 * 1024, "disk_gigabytes": 200}},
		)

	def test_resize_uses_per_host_capacity(self):
		# A resize is gated by its OWN host's headroom (resize_capacity), not the fleet
		# best-host ceiling (capacity). The running size always fits; growth is capped.
		from central.billing.catalog import subscriptions

		sub = subscriptions.create_subscription(TEAM, CLUSTER, plan=SMALL).name  # links an Asset
		cap = self._capacity(4, 8 * 1024, 200)  # fits SMALL, not BIG
		with (
			patch.object(AtlasClient, "resize_capacity", return_value=cap) as mock_resize,
			patch.object(AtlasClient, "capacity") as mock_create,
		):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM, exclude_subscription=sub)
		mock_create.assert_not_called()   # the create-machine ceiling isn't used for a resize
		mock_resize.assert_called_once()  # the per-host resize ceiling is
		plans = _titles(out)
		self.assertIn(SMALL, plans)       # the running size always fits its own host
		self.assertNotIn(BIG, plans)      # growth capped to what the host can seat
		self.assertTrue(out["capacity"]["gated"])

	def test_resize_without_linked_asset_skips_the_gate(self):
		# A subscription with no Asset yet (nothing placed to resize) → don't gate, and
		# don't reach for either capacity endpoint.
		with (
			patch.object(AtlasClient, "resize_capacity") as mock_resize,
			patch.object(AtlasClient, "capacity") as mock_create,
		):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM, exclude_subscription="no-such-sub")
		mock_resize.assert_not_called()
		mock_create.assert_not_called()
		self.assertFalse(out["capacity"]["gated"])
		self.assertIn(BIG, _titles(out))

	def test_flag_off_skips_the_capacity_call(self):
		# validate_capacity off → the full priced menu, and Atlas is never asked.
		frappe.db.set_value("Atlas Instance", CLUSTER, "validate_capacity", 0)
		with patch.object(AtlasClient, "capacity") as mock_capacity:
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		mock_capacity.assert_not_called()
		plans = _titles(out)
		self.assertIn(SMALL, plans)
		self.assertIn(BIG, plans)

	def test_unreachable_atlas_is_fail_soft(self):
		# The capacity call blowing up must not break the menu — show everything and let
		# placement's create-time gate decide.
		with patch.object(AtlasClient, "capacity", side_effect=Exception("atlas down")):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		plans = _titles(out)
		self.assertIn(SMALL, plans)
		self.assertIn(BIG, plans)

	def test_unmeasured_host_admits_everything(self):
		# An unreported axis surfaces as a huge sentinel → every plan fits (uncatalogued
		# = unlimited, the same vouch-by-Active rule placement uses).
		cap = {
			"available": True, "unmeasured": True,
			"largest_vm": {"vcpus": 1024, "memory_megabytes": 1024 * 1024, "disk_gigabytes": 1024 * 1024},
		}
		with patch.object(AtlasClient, "capacity", return_value=cap):
			out = get_eligible_plans(cluster=CLUSTER, team=TEAM)
		plans = _titles(out)
		self.assertIn(SMALL, plans)
		self.assertIn(BIG, plans)
