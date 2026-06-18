# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan Configurator (issue #33).

Two surfaces:
- the single-plan authoring helper (`plans.configure_includes` / `create_configured_plan`)
  — pick a ratio + vCPU, auto-fill memory, write PLAIN quantity/unit into Plan Includes;
- the **ladder generator** (`configurator` + the `Plan Configurator` DocType) — a doubling
  t-shirt ladder of bundles, priced per cluster (all or a selected subset).

Authoring-only resource math: millicores/ratio never reach the data or billing.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import configurator, plans
from central.billing.catalog.pricing import get_catalog_rates, resolve_rate

PLAN = "bundle-configured-test"
PREFIX = "CfgTest"
TEMPLATE = "Cfg Test Template"


def _cleanup():
	for plan in frappe.get_all("Plan", filters={"name": ["like", f"{PREFIX}%"]}, pluck="name"):
		frappe.db.delete("Catalog Rate", {"priced_doctype": "Plan", "priced_for": plan})
		frappe.delete_doc("Plan", plan, force=True, ignore_permissions=True)
	if frappe.db.exists("Plan Configurator", TEMPLATE):
		frappe.delete_doc("Plan Configurator", TEMPLATE, force=True, ignore_permissions=True)


class TestConfigureIncludes(IntegrationTestCase):
	def test_ratio_1_2_derives_memory(self):
		includes = plans.configure_includes(vcpu=0.125, ratio="1:2", disk_gb=10)
		by_type = {r["resource_type"]: r for r in includes}
		self.assertEqual(by_type["Compute"]["quantity"], 0.125)
		self.assertEqual(by_type["Compute"]["unit"], "vCPU")
		self.assertEqual(by_type["Memory"]["quantity"], 0.25)  # 0.125 * 2
		self.assertEqual(by_type["Memory"]["unit"], "GB")
		self.assertEqual(by_type["Disk"]["quantity"], 10)

	def test_ratio_1_4_derives_high_memory(self):
		includes = plans.configure_includes(vcpu=1, ratio="1:4", disk_gb=40)
		memory = next(r for r in includes if r["resource_type"] == "Memory")
		self.assertEqual(memory["quantity"], 4)  # 1 * 4

	def test_memory_override_is_off_ratio(self):
		# 1 vCPU + 3 GB is neither 1:2 nor 1:4 — the override must win.
		includes = plans.configure_includes(vcpu=1, ratio="1:2", disk_gb=20, memory_gb=3)
		memory = next(r for r in includes if r["resource_type"] == "Memory")
		self.assertEqual(memory["quantity"], 3)


class TestCreateConfiguredPlan(IntegrationTestCase):
	def tearDown(self):
		if frappe.db.exists("Plan", PLAN):
			frappe.delete_doc("Plan", PLAN, force=True)

	def test_persists_plain_includes(self):
		plans.create_configured_plan(name=PLAN, title="Configured", vcpu=0.25, ratio="1:2", disk_gb=20)
		doc = frappe.get_doc("Plan", PLAN)
		by_type = {r.resource_type: r for r in doc.includes}
		self.assertEqual(by_type["Compute"].quantity, 0.25)
		self.assertEqual(by_type["Memory"].quantity, 0.5)  # 0.25 * 2
		self.assertEqual(by_type["Disk"].quantity, 20)
		# Plain quantity/unit only — no millicores/ratio stored anywhere.
		self.assertEqual(by_type["Compute"].unit, "vCPU")


class TestBuildLadder(IntegrationTestCase):
	"""The pure authoring math — no DB."""

	def test_doubling_ladder_with_memory_and_disk(self):
		rungs = configurator.build_ladder(0.125, 4, "1:2", base_disk_gb=10, name_prefix=PREFIX)
		self.assertEqual([r["vcpu"] for r in rungs], [0.125, 0.25, 0.5, 1, 2, 4])
		self.assertEqual([r["memory_gb"] for r in rungs], [0.25, 0.5, 1, 2, 4, 8])
		self.assertEqual([r["multiplier"] for r in rungs], [1, 2, 4, 8, 16, 32])
		self.assertEqual([r["disk_gb"] for r in rungs], [10, 20, 40, 80, 160, 320])

	def test_high_memory_ratio(self):
		rungs = configurator.build_ladder(1, 2, "1:4", name_prefix=PREFIX)
		self.assertEqual([r["memory_gb"] for r in rungs], [4, 8])

	def test_memory_optimised_ratios(self):
		self.assertEqual([r["memory_gb"] for r in configurator.build_ladder(1, 2, "1:6")], [6, 12])
		self.assertEqual([r["memory_gb"] for r in configurator.build_ladder(1, 1, "1:8")], [8])

	def test_ratio_for_plan_class(self):
		self.assertEqual(configurator.ratio_for("CPU Optimised", "1:4"), "1:2")
		self.assertEqual(configurator.ratio_for("General", "1:2"), "1:4")
		self.assertEqual(configurator.ratio_for("Memory Optimised", "1:2"), "1:8")
		self.assertEqual(configurator.ratio_for("Custom", "1:6"), "1:6")
		self.assertEqual(configurator.ratio_for(None, "1:4"), "1:4")

	def test_labels_and_names(self):
		rungs = configurator.build_ladder(0.125, 1, "1:2", name_prefix=PREFIX)
		self.assertEqual(rungs[0]["label"], "1/8 vCPU · 0.25 GB")
		self.assertEqual(rungs[0]["name"], f"{PREFIX} 0.125 vCPU 0.25 GB")
		self.assertEqual(rungs[-1]["label"], "1 vCPU · 2 GB")

	def test_no_disk_line_when_base_disk_zero(self):
		rungs = configurator.build_ladder(1, 1, "1:2", base_disk_gb=0, name_prefix=PREFIX)
		types = [i["resource_type"] for i in rungs[0]["includes"]]
		self.assertEqual(types, ["Compute", "Memory"])

	def test_bad_inputs_throw(self):
		with self.assertRaises(frappe.ValidationError):
			configurator.build_ladder(0.125, 4, "1:3")
		with self.assertRaises(frappe.ValidationError):
			configurator.build_ladder(4, 1, "1:2")


class TestGenerate(IntegrationTestCase):
	def setUp(self):
		_cleanup()
		self.cfg = frappe.get_doc({
			"doctype": "Plan Configurator", "template_name": TEMPLATE,
			"plan_class": "Custom", "start_vcpu": 0.125, "ceiling_vcpu": 4,
			"memory_ratio": "1:2", "base_disk_gb": 10, "plan_name_prefix": PREFIX,
			"billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "INR", "base_rate": 100}, {"currency": "USD", "base_rate": 2}],
		}).insert(ignore_permissions=True)

	def tearDown(self):
		_cleanup()

	def test_generate_creates_plans_composition_and_multi_currency_pricing(self):
		out = self.cfg.generate()
		self.assertEqual(len(out["created"]), 6)
		self.cfg.reload()
		self.assertEqual(len(self.cfg.plans), 6)

		# Composition is plain (no millicores / ratio); memory derived, disk scaled.
		plan = frappe.get_doc("Plan", f"{PREFIX} 2 vCPU 4 GB")
		comp = {i.resource_type: i.quantity for i in plan.includes}
		self.assertEqual(comp, {"Compute": 2, "Memory": 4, "Disk": 160})

		# Priced in both currencies at base_rate × multiplier (2 vCPU = ×16).
		self.assertEqual(plan.get_rate("INR"), 1600)
		self.assertEqual(plan.get_rate("USD"), 32)
		# Smallest rung is the base rate itself.
		small = frappe.get_doc("Plan", f"{PREFIX} 0.125 vCPU 0.25 GB")
		self.assertEqual(small.get_rate("INR"), 100)
		self.assertEqual(small.get_rate("USD"), 2)

	def test_preview_is_currency_aware(self):
		data = self.cfg.preview()
		self.assertEqual(data["currencies"], ["INR", "USD"])
		first = data["rungs"][0]  # smallest rung, ×1
		self.assertEqual(
			{x["currency"]: x["rate"] for x in first["rates"]}, {"INR": 100, "USD": 2})

	def test_generate_is_idempotent(self):
		self.cfg.generate()
		out = self.cfg.generate()
		self.assertEqual(len(out["created"]), 0)
		self.assertEqual(len(out["skipped"]), 6)

	def test_apply_pricing_to_cluster_subset_is_selective(self):
		self.cfg.generate()
		small = f"{PREFIX} 0.125 vCPU 0.25 GB"
		big = f"{PREFIX} 2 vCPU 4 GB"

		# Price only the smallest plan, only in INR, on a region.
		out = self.cfg.apply_pricing_to_cluster(
			cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.assertEqual(out[0]["created"], [small])

		# The selected plan has a regional INR rate (100 × 1); the unselected one does not.
		self.assertEqual(resolve_rate(get_catalog_rates("Plan", small), "INR", "ap-south-1"), 100)
		big_rows = get_catalog_rates("Plan", big)
		self.assertFalse([r for r in big_rows if r.cluster == "ap-south-1"])
		# ...but the unselected plan still resolves via its global rate (fallback).
		self.assertEqual(resolve_rate(big_rows, "INR", "ap-south-1"), 1600)
		# USD was not selected, so no regional USD row for the small plan either.
		self.assertFalse(
			[r for r in get_catalog_rates("Plan", small) if r.cluster == "ap-south-1" and r.currency == "USD"])

	def test_reapply_updates_rate_in_place(self):
		self.cfg.generate()
		small = f"{PREFIX} 0.125 vCPU 0.25 GB"
		self.cfg.apply_pricing_to_cluster(cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.cfg.base_rates[0].base_rate = 250  # re-price INR
		out = self.cfg.apply_pricing_to_cluster(cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.assertEqual(out[0]["updated"], [small])
		self.assertEqual(resolve_rate(get_catalog_rates("Plan", small), "INR", "ap-south-1"), 250)
		# No duplicate row was created.
		rows = [r for r in get_catalog_rates("Plan", small)
				if r.cluster == "ap-south-1" and r.currency == "INR"]
		self.assertEqual(len(rows), 1)

	def test_plan_class_drives_ratio_and_composition(self):
		mem = frappe.get_doc({
			"doctype": "Plan Configurator", "template_name": TEMPLATE + " Mem",
			"plan_class": "Memory Optimised", "start_vcpu": 1, "ceiling_vcpu": 1,
			"plan_name_prefix": PREFIX, "billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "INR", "base_rate": 500}],
		}).insert(ignore_permissions=True)
		try:
			mem.generate()
			plan = frappe.get_doc("Plan", f"{PREFIX} 1 vCPU 8 GB")  # 1:8 from the class
			comp = {i.resource_type: i.quantity for i in plan.includes}
			self.assertEqual(comp["Memory"], 8)
		finally:
			frappe.delete_doc("Plan Configurator", TEMPLATE + " Mem", force=True, ignore_permissions=True)
