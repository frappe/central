# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Non-VM product families on the ADR 0007 taxonomy (#77): AI Tokens, SaaS Storage,
Frappe Box Remote Storage — each authored on the masters, billed by the existing spine."""

import frappe

from central.billing.platform.sync import receive_meter_rollups
from central.billing.revenue import metering
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	_clear_metered_plans,
	ensure_team,
	make_metered_plan,
	make_plan,
	seed_running_resource,
)


class TestFamiliesSeed(IntegrationTestCase):
	def test_families_are_seeded_with_rules(self):
		expected = {
			"AI Tokens": ({"Tokens"}, ""),
			"SaaS Storage": ({"Disk"}, ""),
			"Remote Storage": ({"Storage", "Backup"}, "Storage purpose"),
		}
		for name, (allowed, sub_label) in expected.items():
			cat = frappe.get_doc("Plan Category", name)
			self.assertEqual(cat.allowed_types(), allowed)
			self.assertEqual(cat.sub_category_label or "", sub_label)
		self.assertEqual(
			set(frappe.get_all("Plan Sub-Category", {"category": "Remote Storage"}, pluck="name")),
			{"Data", "Backups", "Snapshots"},
		)
		for rt in ("Tokens", "Storage", "Backup"):
			self.assertTrue(frappe.db.exists("Resource Type", rt))


class TestAITokensBilling(IntegrationTestCase):
	"""AI Tokens is a Metered family (ADR 0013/0015): a single metered plan carries BOTH
	the bundled allowance and the per-unit overage rate — one metered plan per resource
	type. Overage bills max(0, used − allowance) × rate off that one plan."""

	TEAM = "team-tokens"
	CLUSTER = "ap-south-1"
	PLAN = "tokens-10m"
	RESOURCE = "tok-res-1"

	def setUp(self):
		ensure_team(self.TEAM)
		# One metered AI Tokens plan: a bundled allowance of 10 (its included quantity, in
		# plain Nos) AND the overage rate of 5 per unit (its Catalog Rate). Clear any
		# leftover metered Tokens plan first so it is the sole one covering the resource.
		_clear_metered_plans("Tokens")
		make_plan(
			self.PLAN,
			category="AI Tokens",
			includes=[{"resource_type": "Tokens", "quantity": 10, "unit": "Nos"}],
			rates=[{"cluster": "", "currency": "INR", "rate": 5}],
		)
		self._purge()
		# Open the resource's billing segment (ADR 0010 — the ledger is the lock) so
		# metering can grandfather its Tokens allowance + rate.
		seed_running_resource(self.TEAM, self.RESOURCE, self.CLUSTER, self.PLAN, rate=0, currency="INR")

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Usage Rollup", {"team": self.TEAM})
		for sub in frappe.get_all("Subscription", {"team": self.TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.delete("Asset", {"team": self.TEAM})
		frappe.db.commit()

	def _meter(self, qty):
		return {
			"resource_id": self.RESOURCE, "resource_type": "Tokens", "meter_type": "Counter",
			"period_start": "2026-06-01 00:00:00", "period_end": "2026-06-30 23:59:59",
			"quantity": qty, "unit": "Nos",
			"idempotency_key": f"{self.RESOURCE}:Counter:2026-06-01", "status": "open",
		}

	def test_overage_above_allowance_bills(self):
		receive_meter_rollups([self._meter(15)])  # 15 used, 10 allowed
		rollup = frappe.get_doc("Usage Rollup", {"resource_id": self.RESOURCE})
		self.assertEqual(rollup.locked_allowance, 10)  # bundled allowance from the plan
		self.assertEqual(rollup.locked_rate, 5)  # from the Tokens metered plan
		lines = metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["quantity"], 5)  # max(0, 15-10)
		self.assertEqual(lines[0]["amount"], 25.0)  # 5 * 5

	def test_within_allowance_bills_nothing(self):
		receive_meter_rollups([self._meter(8)])  # under the 10 allowance
		self.assertEqual(metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30"), [])

	def test_no_compute_anywhere_in_a_tokens_plan(self):
		comp = {i.resource_type for i in frappe.get_doc("Plan", self.PLAN).includes}
		self.assertEqual(comp, {"Tokens"})


class TestSaaSStorage(IntegrationTestCase):
	def test_disk_only_plan_is_sellable(self):
		name = make_plan(
			"saas-100gb",
			category="SaaS Storage",
			includes=[{"resource_type": "Disk", "quantity": 100, "unit": "GB"}],
			rates=[{"cluster": "", "currency": "USD", "rate": 5}],
		)
		plan = frappe.get_doc("Plan", name)
		# The customer surface is storage only — no vCPU/RAM in the composition.
		self.assertEqual({i.resource_type for i in plan.includes}, {"Disk"})
		self.assertEqual(plan.get_rate("USD"), 5)


class TestRemoteStorage(IntegrationTestCase):
	def test_snapshots_plan_is_sellable_and_family_is_live_gauge(self):
		name = make_plan(
			"frappebox-snapshots",
			category="Remote Storage",
			sub_category="Snapshots",
			includes=[{"resource_type": "Storage", "quantity": 0, "unit": "GB"}],
			rates=[{"cluster": "", "currency": "USD", "rate": 1}],
		)
		plan = frappe.get_doc("Plan", name)
		self.assertEqual(plan.sub_category, "Snapshots")
		self.assertEqual(plan.get_rate("USD"), 1)


class TestIPSnapshotAreMeteredOnly(IntegrationTestCase):
	"""IP and Snapshot are valid metered-resource dimensions but never bundle composition."""

	def test_ip_cannot_be_in_a_bundle(self):
		with self.assertRaises(frappe.ValidationError):
			make_plan("bad-ip", includes=[{"resource_type": "IP", "quantity": 1, "unit": "Nos"}])

	def test_snapshot_cannot_be_in_a_tokens_plan(self):
		with self.assertRaises(frappe.ValidationError):
			make_plan(
				"bad-snap", category="AI Tokens",
				includes=[{"resource_type": "Snapshot", "quantity": 1, "unit": "GB"}],
			)

	def test_snapshot_is_valid_as_a_metered_plan(self):
		name = make_metered_plan(
			"meter-snapshot-fam", resource_type="Snapshot",
			pricing_mode="Live", rates=[{"cluster": "", "currency": "USD", "rate": 1}],
		)
		plan = frappe.get_doc("Plan", name)
		self.assertEqual({i.resource_type for i in plan.includes}, {"Snapshot"})
		self.assertEqual(plan.category, "Live Metered Resources")
		self.assertTrue(plan.is_metered_single_resource())
