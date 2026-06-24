# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Add-on folded into a metered single-resource Plan (ADR 0008, issue #78).

The Add-on doctype is gone: a metered resource is priced by a single-resource Plan
under a Metered Plan Category, resolved by its include's resource type. These tests
cover the two guardrails the fold introduced — the one-active-metered-plan-per-resource
uniqueness rule, and surfacing an overage for a resource no metered plan models.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.platform.sync import receive_meter_rollups
from central.billing.revenue import metering
from central.billing.tests.utils import ensure_team, make_metered_plan, make_plan


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
			"meter-uniq-1", resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		dup = _metered_plan_doc("Duplicate Transfer meter", "Transfer")
		with self.assertRaises(frappe.ValidationError):
			dup.insert(ignore_permissions=True)

	def test_inactive_duplicate_is_allowed(self):
		make_metered_plan(
			"meter-uniq-2", resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		# An *inactive* second plan does not collide — only one may be active at a time.
		dup = _metered_plan_doc("Retired Transfer meter", "Transfer", is_active=0)
		dup.insert(ignore_permissions=True)
		self.assertFalse(dup.is_active)

	def test_different_resource_types_coexist(self):
		make_metered_plan(
			"meter-uniq-transfer", resource_type="Transfer",
			rates=[{"cluster": "", "currency": "INR", "rate": 0.5}],
		)
		# A metered plan for a *different* resource is fine.
		name = make_metered_plan(
			"meter-uniq-tokens", resource_type="Tokens",
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
		frappe.get_doc(
			{
				"doctype": "Price Lock", "team": self.TEAM, "plan": self.PLAN,
				"cluster": self.CLUSTER, "resource_id": self.RESOURCE, "currency": "INR",
				"locked_rate": 1000, "started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Usage Rollup", "Price Lock"):
			frappe.db.delete(dt, {"team": self.TEAM})
		frappe.db.commit()

	def _backup_meter(self, qty):
		return {
			"resource_id": self.RESOURCE, "resource_type": "Backup", "meter_type": "Gauge",
			"period_start": "2026-06-01 00:00:00", "period_end": "2026-06-30 23:59:59",
			"quantity": qty, "unit": "GB",
			"idempotency_key": f"{self.RESOURCE}:Backup:2026-06-01", "status": "open",
		}

	def test_overage_with_no_metered_plan_errors(self):
		# 50 GB of Backup usage, no allowance and no metered plan to price it.
		receive_meter_rollups([self._backup_meter(50)])
		with self.assertRaises(frappe.ValidationError):
			metering.metered_line_items(self.TEAM, self.CLUSTER, "2026-06-01", "2026-06-30")
