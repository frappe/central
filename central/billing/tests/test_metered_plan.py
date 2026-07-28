# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Add-on folded into a metered single-resource Plan (ADR 0008, issue #78).

The Add-on doctype is gone: a metered resource is priced by a single-resource Plan
under a Metered Plan Category, resolved by its include's resource type. These tests
cover the two guardrails the fold introduced — the one-active-metered-plan-per-resource
uniqueness rule, and surfacing an overage for a resource no metered plan models.
"""

import frappe

from central.billing.platform.sync import receive_meter_rollups
from central.billing.revenue import metering
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	ensure_team,
	make_metered_plan,
	make_plan,
	seed_running_resource,
)


def _seed_running_purge(team):
	"""Clear a team's rollups + ledger between tests (Price Lock is retired, ADR 0010)."""
	frappe.db.delete("Usage Rollup", {"team": team})
	for sub in frappe.get_all("Subscription", {"team": team}, pluck="name"):
		frappe.db.delete("Subscription Change", {"subscription": sub})
		frappe.db.delete("Subscription", {"name": sub})
	frappe.db.delete("Asset", {"team": team})
	frappe.db.commit()


def _metered_plan_doc(title, resource_type, category="Metered Resources", is_active=1):
	"""A metered single-resource Plan doc (not yet inserted)."""
	return frappe.get_doc(
		{
			"doctype": "Plan",
			"title": title,
			"category": category,
			"billing_cycle": "Monthly",
			"is_active": is_active,
			"includes": [{"resource_type": resource_type, "quantity": 0, "unit": "GB"}],
		}
	)


class TestMeteredPlanUniqueness(IntegrationTestCase):
	"""At most one *active* metered single-resource Plan per resource type, so metering's
	resolution is unambiguous (the old global Add-on lookup silently picked one)."""

	def test_second_active_metered_plan_for_resource_rejected(self):
		make_metered_plan(
			"meter-uniq-1",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		dup = _metered_plan_doc("Duplicate Transfer meter", "Transfer")
		with self.assertRaises(frappe.ValidationError):
			dup.insert(ignore_permissions=True)

	def test_inactive_duplicate_is_allowed(self):
		make_metered_plan(
			"meter-uniq-2",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		# An *inactive* second plan does not collide — only one may be active at a time.
		dup = _metered_plan_doc("Retired Transfer meter", "Transfer", is_active=0)
		dup.insert(ignore_permissions=True)
		self.assertFalse(dup.is_active)

	def test_different_resource_types_coexist(self):
		make_metered_plan(
			"meter-uniq-transfer",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		# A metered plan for a *different* resource is fine.
		name = make_metered_plan(
			"meter-uniq-tokens",
			resource_type="Tokens",
			rates=[{"cluster": "", "currency": "INR", "rate": 5}],
		)
		self.assertTrue(frappe.get_doc("Plan", name).is_metered_single_resource())


class TestUnmodelledMeteredResource(IntegrationTestCase):
	"""A metered overage for a resource no metered plan prices is a misconfiguration —
	it must error, not bill silently at a zero rate (ADR 0008)."""

	TEAM = "team-unmodelled"
	CLUSTER = "ap-south-1"
	PLAN = "bundle-unmodelled"
	RESOURCE = "srv-unmodelled"

	def setUp(self):
		ensure_team(self.TEAM)
		make_plan(self.PLAN, includes=[{"resource_type": "Transfer", "quantity": 100, "unit": "GB"}])
		# Deliberately leave "Backup" unmodelled: no metered plan prices it.
		from central.billing.tests.utils import _clear_metered_plans

		_clear_metered_plans("Backup")
		self._purge()
		seed_running_resource(self.TEAM, self.RESOURCE, self.CLUSTER, self.PLAN, rate=1000, currency="INR")

	def tearDown(self):
		self._purge()

	def _purge(self):
		_seed_running_purge(self.TEAM)

	def _backup_meter(self, qty):
		return {
			"resource_id": self.RESOURCE,
			"resource_type": "Backup",
			"meter_type": "Gauge",
			"period_start": "2026-06-01 00:00:00",
			"period_end": "2026-06-30 23:59:59",
			"quantity": qty,
			"unit": "GB",
			"idempotency_key": f"{self.RESOURCE}:Backup:2026-06-01",
			"status": "open",
		}

	def test_overage_with_no_metered_plan_errors(self):
		# 50 GB of Backup usage, no allowance and no metered plan to price it.
		receive_meter_rollups([self._backup_meter(50)])
		with self.assertRaises(frappe.ValidationError):
			metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30")


class TestFreeTierMeteredResource(IntegrationTestCase):
	"""A metered plan whose rate row is configured at 0 is a legitimate free tier — its
	overage bills a zero-amount line, NOT a 'no active metered plan' error. This is the
	case the old `if not rate` guard conflated with a genuine misconfiguration (ADR 0008)."""

	TEAM = "team-freetier"
	CLUSTER = "ap-south-1"
	PLAN = "bundle-freetier"
	RESOURCE = "srv-freetier"

	def setUp(self):
		ensure_team(self.TEAM)
		# Base bundle gives Transfer a zero allowance, so all usage is overage.
		make_plan(self.PLAN, includes=[{"resource_type": "Transfer", "quantity": 0, "unit": "GB"}])
		# A metered plan that DOES price Transfer — at a rate of 0 (free tier).
		make_metered_plan(
			"meter-freetier",
			resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0}],
		)
		self._purge()
		seed_running_resource(self.TEAM, self.RESOURCE, self.CLUSTER, self.PLAN, rate=1000, currency="INR")

	def tearDown(self):
		self._purge()
		from central.billing.tests.utils import _clear_metered_plans

		_clear_metered_plans("Transfer")
		frappe.db.commit()

	def _purge(self):
		_seed_running_purge(self.TEAM)

	def _transfer_meter(self, qty):
		return {
			"resource_id": self.RESOURCE,
			"resource_type": "Transfer",
			"meter_type": "Gauge",
			"period_start": "2026-06-01 00:00:00",
			"period_end": "2026-06-30 23:59:59",
			"quantity": qty,
			"unit": "GB",
			"idempotency_key": f"{self.RESOURCE}:Transfer:2026-06-01",
			"status": "open",
		}

	def test_zero_priced_overage_bills_a_zero_line(self):
		receive_meter_rollups([self._transfer_meter(50)])
		lines = metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30")
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0]["resource_type"], "Transfer")
		self.assertEqual(lines[0]["quantity"], 50)
		self.assertEqual(lines[0]["rate"], 0)
		self.assertEqual(lines[0]["amount"], 0)
