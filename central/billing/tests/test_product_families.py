# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Non-VM product families on the ADR 0007 taxonomy (#77): AI Tokens, SaaS Storage,
Frappe Box Remote Storage — each authored on the masters, billed by the existing spine."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.platform.sync import receive_meter_rollups, receive_usage_events
from central.billing.revenue import metering
from central.billing.tests.utils import ensure_team, make_addon, make_plan


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
	"""Tokens 'metered or bundled or both' = the existing allowance + overage path."""

	TEAM = "team-tokens"
	CLUSTER = "ap-south-1"
	PLAN = "tokens-10m"
	RESOURCE = "tok-res-1"

	def setUp(self):
		ensure_team(self.TEAM)
		# A bundled 10M-token allowance; metered overage at 5 / 1M tokens.
		make_plan(
			self.PLAN,
			category="AI Tokens",
			includes=[{"resource_type": "Tokens", "quantity": 10, "unit": "1M tokens"}],
		)
		make_addon(
			"addon-tokens-meter",
			resource_type="Tokens",
			billing_type="Metered",
			unit="1M tokens",
			rates=[{"cluster": "", "currency": "INR", "rate": 5}],
		)
		self._purge()
		receive_usage_events([{
			"event_id": "ev-tok", "team": self.TEAM, "resource_id": self.RESOURCE,
			"cluster": self.CLUSTER, "plan": self.PLAN, "shown_rate": 0, "currency": "INR",
			"event_type": "subscribed", "effective_from": "2026-06-01 00:00:00", "effective_to": None,
		}])

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Usage Rollup", "Price Lock"):
			frappe.db.delete(dt, {"team": self.TEAM})
		frappe.db.commit()

	def _meter(self, qty):
		return {
			"resource_id": self.RESOURCE, "resource_type": "Tokens", "meter_type": "Counter",
			"period_start": "2026-06-01 00:00:00", "period_end": "2026-06-30 23:59:59",
			"quantity": qty, "unit": "1M tokens",
			"idempotency_key": f"{self.RESOURCE}:Counter:2026-06-01", "status": "open",
		}

	def test_overage_above_allowance_bills(self):
		receive_meter_rollups([self._meter(15)])  # 15M used, 10M allowed
		rollup = frappe.get_doc("Usage Rollup", {"resource_id": self.RESOURCE})
		self.assertEqual(rollup.locked_allowance, 10)  # bundled allowance from the plan
		self.assertEqual(rollup.locked_rate, 5)  # from the Tokens add-on
		lines = metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["quantity"], 5)  # max(0, 15-10)
		self.assertEqual(lines[0]["amount"], 25.0)  # 5 * 5

	def test_within_allowance_bills_nothing(self):
		receive_meter_rollups([self._meter(8)])  # under the 10M allowance
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
			includes=[{"resource_type": "Storage", "quantity": 0, "unit": "GB-day"}],
			rates=[{"cluster": "", "currency": "USD", "rate": 1}],
		)
		plan = frappe.get_doc("Plan", name)
		self.assertEqual(plan.sub_category, "Snapshots")
		self.assertEqual(plan.get_rate("USD"), 1)


class TestIPSnapshotAreAddOnsOnly(IntegrationTestCase):
	"""IP and Snapshot are valid add-on dimensions but never bundle composition."""

	def test_ip_cannot_be_in_a_bundle(self):
		with self.assertRaises(frappe.ValidationError):
			make_plan("bad-ip", includes=[{"resource_type": "IP", "quantity": 1, "unit": "unit"}])

	def test_snapshot_cannot_be_in_a_tokens_plan(self):
		with self.assertRaises(frappe.ValidationError):
			make_plan(
				"bad-snap", category="AI Tokens",
				includes=[{"resource_type": "Snapshot", "quantity": 1, "unit": "GB"}],
			)

	def test_snapshot_is_valid_as_an_addon(self):
		name = make_addon(
			"addon-snapshot-fam", resource_type="Snapshot", billing_type="Metered",
			pricing_mode="Live", rates=[{"cluster": "", "currency": "USD", "rate": 1}],
		)
		self.assertEqual(frappe.db.get_value("Add-on", name, "resource_type"), "Snapshot")
