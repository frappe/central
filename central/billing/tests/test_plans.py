# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog.plans import get_plan_pricing
from central.billing.catalog.pricing import set_catalog_rates
from central.billing.tests.utils import make_plan


class TestGetPlanPricing(IntegrationTestCase):
	def test_resolves_rate_per_currency(self):
		make_plan("bundle-test-2vcpu")

		usd = get_plan_pricing(plan="bundle-test-2vcpu", currency="USD")
		inr = get_plan_pricing(plan="bundle-test-2vcpu", currency="INR")

		self.assertEqual(usd["plan"], "bundle-test-2vcpu")
		self.assertEqual(usd["rate"], 40)
		self.assertEqual(inr["rate"], 3200)

	def test_regional_override_resolves(self):
		make_plan(
			"bundle-test-region",
			rates=[
				{"cluster": "", "currency": "INR", "rate": 3200},
				{"cluster": "ap-south-1", "currency": "INR", "rate": 3500},
			],
		)
		pricing = get_plan_pricing(plan="bundle-test-region", currency="INR", cluster="ap-south-1")
		self.assertEqual(pricing["rate"], 3500)

	def test_includes_are_composition_only_no_price(self):
		make_plan("bundle-test-includes")
		pricing = get_plan_pricing(plan="bundle-test-includes")

		includes = pricing["includes"]
		self.assertEqual(len(includes), 3)
		self.assertEqual(includes[0]["resource_type"], "Compute")
		# composition rows carry quantity/unit but no price/rate
		self.assertNotIn("rate", includes[0])
		self.assertNotIn("price_per_unit", includes[0])


class TestPlanIdentity(IntegrationTestCase):
	def test_rate_edit_does_not_fork_a_new_plan(self):
		name = make_plan("bundle-test-rate-edit")
		count_before = frappe.db.count("Plan")

		# A rate change is editing the plan's Catalog Rate documents, not the plan.
		set_catalog_rates(
			"Plan",
			name,
			[{"cluster": "", "currency": "USD", "rate": 99}, {"cluster": "", "currency": "INR", "rate": 3200}],
		)

		self.assertEqual(frappe.db.count("Plan"), count_before)
		self.assertEqual(get_plan_pricing(plan=name, currency="USD")["rate"], 99)


class TestPlanRequiresIncludes(IntegrationTestCase):
	"""A Plan must declare what it bills — at least one Plan Includes row (#85)."""

	def test_empty_includes_is_rejected(self):
		doc = frappe.get_doc(
			{
				"doctype": "Plan",
				"title": "Empty Plan",
				"category": "VM Plans",
				"billing_cycle": "Monthly",
				"is_active": 1,
				"includes": [],
			}
		)
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_one_include_is_accepted(self):
		doc = frappe.get_doc(
			{
				"doctype": "Plan",
				"title": "One-Include Plan",
				"category": "VM Plans",
				"billing_cycle": "Monthly",
				"is_active": 1,
				"includes": [{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"}],
			}
		)
		doc.insert(ignore_permissions=True)
		self.assertEqual(len(doc.includes), 1)
