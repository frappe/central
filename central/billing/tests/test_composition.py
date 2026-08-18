# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Composed-config shape validation against the optimisation profile (#81)."""

import frappe

from central.billing.catalog.composition import (
	composition_quantities,
	parse_vcpu_steps,
	validate_composition,
)
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


def _config(vcpu, ram, disk=None):
	rows = [
		{"resource_type": "Compute", "quantity": vcpu},
		{"resource_type": "Memory", "quantity": ram},
	]
	if disk is not None:
		rows.append({"resource_type": "Disk", "quantity": disk})
	return rows


class TestCompositionValidation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# A controlled profile (1:2, steps 1,2,4,8, disk 10..100) so the asserts don't
		# depend on the shipped seed values.
		cls.profile = "Test 1:2 Profile"
		if not frappe.db.exists("Plan Sub-Category", cls.profile):
			frappe.get_doc(
				{
					"doctype": "Plan Sub-Category",
					"sub_category_name": cls.profile,
					"category": "VM Plans",
					"ram_ratio": 2,
					"vcpu_steps": "1,2,4,8",
					"disk_min": 10,
					"disk_max": 100,
				}
			).insert(ignore_permissions=True)

	def test_parse_vcpu_steps(self):
		self.assertEqual(parse_vcpu_steps("1,2,4,8"), [1, 2, 4, 8])
		self.assertEqual(parse_vcpu_steps(" 8, 1 ,2 "), [1, 2, 8])
		self.assertEqual(parse_vcpu_steps(None), [])

	def test_composition_quantities_sums_by_type(self):
		qty = composition_quantities(_config(2, 4, 40))
		self.assertEqual(qty, {"Compute": 2, "Memory": 4, "Disk": 40})

	def test_valid_on_ratio_in_bounds_passes(self):
		validate_composition(self.profile, _config(2, 4, 40))  # 4 == 2 x 2, disk in [10,100]

	def test_off_ratio_ram_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_composition(self.profile, _config(2, 6, 40))  # 6 != 2 x 2

	def test_vcpu_not_in_steps_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_composition(self.profile, _config(3, 6, 40))  # 3 not a step

	def test_disk_below_min_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_composition(self.profile, _config(2, 4, 5))

	def test_disk_above_max_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_composition(self.profile, _config(2, 4, 500))

	def test_seeded_general_profile(self):
		# Shipped General is ratio 4: 2 vCPU needs 8 GB, not 4.
		validate_composition("General", _config(2, 8, 40))
		with self.assertRaises(frappe.ValidationError):
			validate_composition("General", _config(2, 4, 40))

	def test_seeded_memory_optimised_profile(self):
		# Shipped Memory Optimised is ratio 8: 2 vCPU needs 16 GB.
		validate_composition("Memory Optimised", _config(2, 16, 40))

	def test_unknown_profile_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			validate_composition("No Such Profile", _config(2, 4, 40))
