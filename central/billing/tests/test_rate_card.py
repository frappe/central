# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Composed-config component rate card — Resource Type priced via Catalog Rate (#79)."""

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.catalog.pricing import (
	resolve_component_rate,
	resolve_config_rate,
	set_catalog_rate,
)
from central.billing.catalog.rate_card import ensure_component_rate_card


class TestComponentRateCard(IntegrationTestCase):
	def setUp(self):
		ensure_component_rate_card()

	def test_resource_type_is_a_priceable_catalog_rate(self):
		"""A Catalog Rate can price a Resource Type with an optional cluster + per-unit rate."""
		name, _ = set_catalog_rate("Resource Type", "Compute", "INR", 500, cluster="ap-south-1")
		row = frappe.get_doc("Catalog Rate", name)
		self.assertEqual(row.priced_doctype, "Resource Type")
		self.assertEqual(row.priced_for, "Compute")
		self.assertEqual(row.cluster, "ap-south-1")
		self.assertEqual(row.rate, 500)

	def test_plan_only_doctype_still_rejected(self):
		"""A non-priceable parent is refused (the Dynamic Link guard)."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Catalog Rate",
					"priced_doctype": "Team",
					"priced_for": "Compute",
					"currency": "INR",
					"rate": 1,
				}
			).insert(ignore_permissions=True)

	def test_component_rate_regional_over_global(self):
		set_catalog_rate("Resource Type", "Compute", "INR", 500)  # global
		set_catalog_rate("Resource Type", "Compute", "INR", 550, cluster="ap-south-1")
		self.assertEqual(resolve_component_rate("Compute", "INR", "ap-south-1"), 550)
		# A cluster with no regional row falls back to the global rate.
		self.assertEqual(resolve_component_rate("Compute", "INR", "us-east-1"), 500)

	def test_missing_currency_is_no_rate_not_zero(self):
		self.assertIsNone(resolve_component_rate("Compute", "JPY"))

	def test_starter_card_seeded_for_shipped_currencies(self):
		for currency in ("INR", "USD"):
			for resource_type in ("Compute", "Memory", "Disk"):
				self.assertIsNotNone(
					resolve_component_rate(resource_type, currency),
					f"{resource_type} not seeded for {currency}",
				)

	def test_config_rate_is_sum_of_parts(self):
		"""Σ(qty × component_rate) for 2 vCPU · 4 GB · 40 GB against the seeded INR card."""
		includes = [
			{"resource_type": "Compute", "quantity": 2},
			{"resource_type": "Memory", "quantity": 4},
			{"resource_type": "Disk", "quantity": 40},
		]
		# Seeded INR: Compute 500, Memory 250, Disk 10 -> 1000 + 1000 + 400 = 2400.
		self.assertEqual(resolve_config_rate(includes, "INR"), 2400)

	def test_config_rate_none_when_a_part_is_unpriced(self):
		includes = [
			{"resource_type": "Compute", "quantity": 2},
			{"resource_type": "Memory", "quantity": 4},
		]
		self.assertIsNone(resolve_config_rate(includes, "JPY"))

	def test_admin_endpoint_sets_a_component_rate(self):
		from central.billing.api.admin.catalog import update_component_rate

		frappe.set_user("Administrator")
		out = update_component_rate("Disk", "INR", 12, cluster="ap-south-1")
		self.assertEqual(out["rate"], 12)
		self.assertEqual(resolve_component_rate("Disk", "INR", "ap-south-1"), 12)
