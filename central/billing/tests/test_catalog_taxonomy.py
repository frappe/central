# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog taxonomy masters — Plan Category / Sub-Category / Resource Type (#75, ADR 0007)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import configurator
from central.billing.tests.utils import make_plan


class TestCatalogTaxonomy(IntegrationTestCase):
	def test_vm_taxonomy_is_seeded(self):
		"""The v15 patch seeds the current VM family so nothing in flight breaks."""
		self.assertTrue(frappe.db.exists("Plan Category", "VM Plans"))
		vm = frappe.get_doc("Plan Category", "VM Plans")
		self.assertEqual(vm.configurator_builder, "vm_rungs")
		self.assertEqual(vm.sub_category_label, "Optimization profile")
		self.assertEqual(vm.allowed_types(), {"Compute", "Memory", "Disk", "Transfer"})
		for rt in ("Compute", "Memory", "Disk", "Transfer"):
			self.assertTrue(frappe.db.exists("Resource Type", rt))
		for sc in ("General", "CPU Optimised", "Memory Optimised", "Storage Optimised"):
			self.assertEqual(frappe.db.get_value("Plan Sub-Category", sc, "category"), "VM Plans")

	def test_plan_defaults_to_vm_plans_category(self):
		"""make_plan passes no category; the field default keeps VM authoring working."""
		name = make_plan("bundle-tax-default")
		self.assertEqual(frappe.db.get_value("Plan", name, "category"), "VM Plans")

	def test_plan_class_column_is_gone(self):
		self.assertFalse("plan_class" in frappe.get_meta("Plan").get_valid_columns())

	def test_off_family_resource_type_is_rejected(self):
		"""A VM plan can't include Snapshot — it's not in the family's allow-list."""
		with self.assertRaises(frappe.ValidationError):
			make_plan(
				"bundle-tax-offfamily",
				includes=[{"resource_type": "Snapshot", "quantity": 1, "unit": "GB"}],
			)

	def test_allowed_resource_type_passes(self):
		name = make_plan(
			"bundle-tax-allowed",
			includes=[{"resource_type": "Compute", "quantity": 1, "unit": "vCPU"}],
		)
		self.assertTrue(frappe.db.exists("Plan", name))

	def test_unconstrained_category_skips_the_check(self):
		"""A category with a blank allow-list leaves composition unconstrained."""
		_ensure_category("Open Family", allowed=[])
		name = make_plan(
			"bundle-tax-open",
			category="Open Family",
			includes=[{"resource_type": "Snapshot", "quantity": 1, "unit": "GB"}],
		)
		self.assertTrue(frappe.db.exists("Plan", name))

	def test_sub_category_must_belong_to_the_plans_category(self):
		"""A sub-category from another family is rejected (ADR 0007)."""
		_ensure_category("Other Family", allowed=[], sub_label="Variant")
		_ensure_sub_category("Foreign Variant", "Other Family")
		with self.assertRaises(frappe.ValidationError):
			make_plan("bundle-tax-foreign-sub", sub_category="Foreign Variant")

	def test_matching_sub_category_is_accepted(self):
		name = make_plan("bundle-tax-good-sub", sub_category="CPU Optimised")
		self.assertEqual(frappe.db.get_value("Plan", name, "sub_category"), "CPU Optimised")

	def test_configurator_sets_category_and_maps_sub_category(self):
		"""generate_plans authors the VM family and carries plan_class -> sub_category."""
		configurator.generate_plans(
			"Memory Optimised",
			rungs=[{"plan_name": "tax-cfg-mem", "label": "Mem", "vcpu": 1, "memory_gb": 4, "disk_gb": 20, "transfer_gb": 0}],
		)
		self.assertEqual(frappe.db.get_value("Plan", "tax-cfg-mem", "category"), "VM Plans")
		self.assertEqual(frappe.db.get_value("Plan", "tax-cfg-mem", "sub_category"), "Memory Optimised")

	def test_configurator_custom_class_carries_no_sub_category(self):
		configurator.generate_plans(
			"Custom",
			rungs=[{"plan_name": "tax-cfg-custom", "label": "Cust", "vcpu": 1, "memory_gb": 2, "disk_gb": 10, "transfer_gb": 0}],
		)
		self.assertEqual(frappe.db.get_value("Plan", "tax-cfg-custom", "category"), "VM Plans")
		self.assertIsNone(frappe.db.get_value("Plan", "tax-cfg-custom", "sub_category"))


def _ensure_category(name, *, allowed, sub_label=None):
	if frappe.db.exists("Plan Category", name):
		return
	frappe.get_doc(
		{
			"doctype": "Plan Category",
			"category_name": name,
			"configurator_builder": "simple",
			"default_billing_type": "Fixed",
			"sub_category_label": sub_label,
			"allowed_resource_types": [{"resource_type": rt} for rt in allowed],
		}
	).insert(ignore_permissions=True)


def _ensure_sub_category(name, category):
	if not frappe.db.exists("Plan Sub-Category", name):
		frappe.get_doc(
			{"doctype": "Plan Sub-Category", "sub_category_name": name, "category": category}
		).insert(ignore_permissions=True)
