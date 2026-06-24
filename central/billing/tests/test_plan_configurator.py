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

PREFIX = "CfgTest"
TEMPLATE = "Cfg Test Template"


def _cleanup():
	# Plans are hash-named now, so they're reached through the configurators' links.
	for t in frappe.get_all("Plan Configurator", filters={"template_name": ["like", "Cfg%"]}, pluck="name"):
		doc = frappe.get_doc("Plan Configurator", t)
		for row in list(doc.rungs) + list(doc.simple_plans):
			if row.plan and frappe.db.exists("Plan", row.plan):
				frappe.db.delete("Catalog Rate", {"priced_doctype": "Plan", "priced_for": row.plan})
				frappe.delete_doc("Plan", row.plan, force=True, ignore_permissions=True)
		frappe.delete_doc("Plan Configurator", t, force=True, ignore_permissions=True)


def _plan_for(cfg, plan_name):
	"""The hash-named Plan a rung (identified by its human plan_name) generated."""
	cfg.reload()
	row = next(r for r in cfg.rungs if r.plan_name == plan_name)
	return frappe.get_doc("Plan", row.plan)


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
		if getattr(self, "created", None) and frappe.db.exists("Plan", self.created):
			frappe.delete_doc("Plan", self.created, force=True)

	def test_persists_plain_includes(self):
		# Plan is hash-named; create_configured_plan returns the minted name.
		self.created = plans.create_configured_plan(title="Configured", vcpu=0.25, ratio="1:2", disk_gb=20)
		doc = frappe.get_doc("Plan", self.created)
		self.assertEqual(doc.title, "Configured")
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

	def test_transfer_steps_additively(self):
		rungs = configurator.build_ladder(2, 16, "1:4", base_transfer_gb=4000, transfer_step_gb=1000)
		self.assertEqual([r["transfer_gb"] for r in rungs], [4000, 5000, 6000, 7000])

	def test_ratio_for_sub_category(self):
		self.assertEqual(configurator.ratio_for("CPU Optimised", "1:4"), "1:2")
		self.assertEqual(configurator.ratio_for("General", "1:2"), "1:4")
		self.assertEqual(configurator.ratio_for("Memory Optimised", "1:2"), "1:8")
		self.assertEqual(configurator.ratio_for("Storage Optimised", "1:2"), "1:8")
		self.assertEqual(configurator.ratio_for("Custom", "1:6"), "1:6")
		self.assertEqual(configurator.ratio_for(None, "1:4"), "1:4")

	def test_labels_and_names(self):
		rungs = configurator.build_ladder(0.125, 1, "1:2", name_prefix=PREFIX)
		self.assertEqual(rungs[0]["label"], "1/8 vCPU · 0.25 GB")
		self.assertEqual(rungs[0]["plan_name"], f"{PREFIX} 0.125 vCPU 0.25 GB")
		self.assertEqual(rungs[-1]["label"], "1 vCPU · 2 GB")

	def test_rung_includes_skips_zero_disk_and_transfer(self):
		self.assertEqual(
			[r["resource_type"] for r in configurator.rung_includes(1, 2, 0, 0)],
			["Compute", "Memory"])
		self.assertEqual(
			[r["resource_type"] for r in configurator.rung_includes(1, 2, 25, 4000)],
			["Compute", "Memory", "Disk", "Transfer"])

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
			"start_vcpu": 0.125, "ceiling_vcpu": 4,
			"memory_ratio": "1:2", "base_disk_gb": 10, "plan_name_prefix": PREFIX,
			"billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "INR", "base_rate": 100}, {"currency": "USD", "base_rate": 2}],
		}).insert(ignore_permissions=True)

	def tearDown(self):
		_cleanup()

	def _generate(self, **kw):
		self.cfg.populate_rungs()
		return self.cfg.generate_and_price(**kw)

	def test_generate_creates_plans_composition_and_multi_currency_pricing(self):
		out = self._generate()
		self.assertEqual(len(out["created"]), 6)
		self.cfg.reload()
		self.assertEqual(len(self.cfg.rungs), 6)
		self.assertTrue(all(r.plan for r in self.cfg.rungs))  # each rung links its Plan

		# Composition is plain (no millicores / ratio); memory derived, disk scaled.
		plan = _plan_for(self.cfg, f"{PREFIX} 2 vCPU 4 GB")
		comp = {i.resource_type: i.quantity for i in plan.includes}
		self.assertEqual(comp, {"Compute": 2, "Memory": 4, "Disk": 160})
		# Title carries the profile + resource info; the name is an opaque hash.
		self.assertEqual(plan.title, "VM Plans — 2 vCPU · 4 GB")
		self.assertNotEqual(plan.name, plan.title)

		# Priced in both currencies at base_rate × multiplier (2 vCPU = ×16).
		self.assertEqual(plan.get_rate("INR"), 1600)
		self.assertEqual(plan.get_rate("USD"), 32)
		# Smallest rung is the base rate itself.
		small = _plan_for(self.cfg, f"{PREFIX} 0.125 vCPU 0.25 GB")
		self.assertEqual(small.get_rate("INR"), 100)
		self.assertEqual(small.get_rate("USD"), 2)

	def test_preview_is_currency_aware(self):
		data = self.cfg.preview()  # works off the formula before rungs exist
		self.assertEqual(data["currencies"], ["INR", "USD"])
		first = data["rungs"][0]  # smallest rung, ×1
		self.assertEqual(
			{x["currency"]: x["rate"] for x in first["rates"]}, {"INR": 100, "USD": 2})

	def test_edited_rung_is_honoured(self):
		# Populate, then hand-edit a rung's memory off-ratio before generating.
		self.cfg.populate_rungs()
		row = next(r for r in self.cfg.rungs if r.plan_name == f"{PREFIX} 1 vCPU 2 GB")
		row.memory_gb = 3  # off-ratio override
		self.cfg.save(ignore_permissions=True)
		self.cfg.generate_and_price()
		plan = _plan_for(self.cfg, f"{PREFIX} 1 vCPU 2 GB")
		mem = next(i for i in plan.includes if i.resource_type == "Memory")
		self.assertEqual(mem.quantity, 3)

	def test_add_custom_rung_between_sizes(self):
		# A hand-added 1 vCPU / 3 GB rung (between the 2 GB and 4 GB rungs) names and
		# prices itself on save, then generates like any other.
		self.cfg.populate_rungs()
		self.cfg.append("rungs", {"vcpu": 1, "memory_gb": 3})
		self.cfg.save(ignore_permissions=True)
		added = next(r for r in self.cfg.rungs if r.vcpu == 1 and r.memory_gb == 3)
		self.assertEqual(added.plan_name, f"{PREFIX} 1 vCPU 3 GB")  # auto-derived
		self.assertEqual(added.multiplier, 8)  # 1 / 0.125 start

		self.cfg.generate_and_price()
		plan = _plan_for(self.cfg, f"{PREFIX} 1 vCPU 3 GB")
		self.assertEqual(
			next(i.quantity for i in plan.includes if i.resource_type == "Memory"), 3)
		self.assertEqual(plan.get_rate("INR"), 800)  # 100 × 8

	def test_generate_is_idempotent(self):
		self._generate()
		out = self.cfg.generate_and_price()
		self.assertEqual(len(out["created"]), 0)
		self.assertEqual(len(out["skipped"]), 6)

	def test_per_cluster_subset_is_selective(self):
		self._generate()  # global rates for all rungs
		small = f"{PREFIX} 0.125 vCPU 0.25 GB"
		big = f"{PREFIX} 2 vCPU 4 GB"
		small_id = _plan_for(self.cfg, small).name
		big_id = _plan_for(self.cfg, big).name

		# Generate again for a region, only the smallest plan, only in INR. Selection is
		# still by the rung's human plan_name; the priced/created ids are the hashes.
		out = self.cfg.generate_and_price(cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.assertEqual(out["pricing"][0]["created"], [small_id])

		# The selected plan has a regional INR rate (100 × 1); the unselected one does not.
		self.assertEqual(resolve_rate(get_catalog_rates("Plan", small_id), "INR", "ap-south-1"), 100)
		big_rows = get_catalog_rates("Plan", big_id)
		self.assertFalse([r for r in big_rows if r.cluster == "ap-south-1"])
		# ...but the unselected plan still resolves via its global rate (fallback).
		self.assertEqual(resolve_rate(big_rows, "INR", "ap-south-1"), 1600)
		# USD was not selected, so no regional USD row for the small plan either.
		self.assertFalse(
			[r for r in get_catalog_rates("Plan", small_id) if r.cluster == "ap-south-1" and r.currency == "USD"])

	def test_reprice_cluster_updates_rate_in_place(self):
		self._generate()
		small = f"{PREFIX} 0.125 vCPU 0.25 GB"
		small_id = _plan_for(self.cfg, small).name
		self.cfg.generate_and_price(cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.cfg.base_rates[0].base_rate = 250  # re-price INR
		out = self.cfg.generate_and_price(cluster="ap-south-1", currencies=["INR"], plans=[small])
		self.assertEqual(out["pricing"][0]["updated"], [small_id])
		self.assertEqual(resolve_rate(get_catalog_rates("Plan", small_id), "INR", "ap-south-1"), 250)
		# No duplicate row was created.
		rows = [r for r in get_catalog_rates("Plan", small_id)
				if r.cluster == "ap-south-1" and r.currency == "INR"]
		self.assertEqual(len(rows), 1)

	def test_run_generation_job(self):
		# The background entrypoint loads the doc and does the work synchronously.
		from central.billing.doctype.plan_configurator.plan_configurator import run_generation

		self.cfg.populate_rungs()
		out = run_generation(self.cfg.name, cluster=None, plans=[f"{PREFIX} 1 vCPU 2 GB"])
		self.cfg.reload()
		row = next(r for r in self.cfg.rungs if r.plan_name == f"{PREFIX} 1 vCPU 2 GB")
		self.assertTrue(row.plan and frappe.db.exists("Plan", row.plan))
		self.assertEqual(out["created"], [row.plan])

	def test_sub_category_drives_ratio_and_composition(self):
		mem = frappe.get_doc({
			"doctype": "Plan Configurator", "template_name": "Cfg Test Mem",
			"sub_category": "Memory Optimised", "start_vcpu": 1, "ceiling_vcpu": 1,
			"plan_name_prefix": PREFIX, "billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "INR", "base_rate": 500}],
		}).insert(ignore_permissions=True)
		mem.populate_rungs()
		mem.generate_and_price()
		plan = _plan_for(mem, f"{PREFIX} 1 vCPU 8 GB")  # 1:8 from the class
		comp = {i.resource_type: i.quantity for i in plan.includes}
		self.assertEqual(comp["Memory"], 8)
		self.assertEqual(plan.sub_category, "Memory Optimised")

	def test_reproduces_general_purpose_family(self):
		# DigitalOcean's General Purpose ladder, exactly (USD): the configurator's
		# formula reproduces vCPU/RAM/disk/transfer/price across the rungs.
		gp = frappe.get_doc({
			"doctype": "Plan Configurator", "template_name": "Cfg Test GP",
			"sub_category": "General", "start_vcpu": 2, "ceiling_vcpu": 16,
			"base_disk_gb": 25, "base_transfer_gb": 4000, "transfer_step_gb": 1000,
			"plan_name_prefix": "CfgGP", "billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "USD", "base_rate": 63}],
		}).insert(ignore_permissions=True)
		gp.populate_rungs()
		gp.generate_and_price()

		entry = _plan_for(gp, "CfgGP 2 vCPU 8 GB")  # $63
		self.assertEqual(
			{i.resource_type: i.quantity for i in entry.includes},
			{"Compute": 2, "Memory": 8, "Disk": 25, "Transfer": 4000})
		self.assertEqual(entry.get_rate("USD"), 63)

		top = _plan_for(gp, "CfgGP 16 vCPU 64 GB")  # $504
		self.assertEqual(
			{i.resource_type: i.quantity for i in top.includes},
			{"Compute": 16, "Memory": 64, "Disk": 200, "Transfer": 7000})
		self.assertEqual(top.get_rate("USD"), 504)


class TestSimpleBuilder(IntegrationTestCase):
	"""The `simple` builder authors non-VM families (AI Tokens here) — no sizing math,
	one include from the family's resource type, hash-named, priced by multiplier."""

	CATEGORY = "Cfg AI Tokens"

	def setUp(self):
		_cleanup()
		if not frappe.db.exists("Resource Type", "Tokens"):
			frappe.get_doc({"doctype": "Resource Type", "resource_type_name": "Tokens"}).insert(ignore_permissions=True)
		if not frappe.db.exists("Plan Category", self.CATEGORY):
			frappe.get_doc({
				"doctype": "Plan Category", "category_name": self.CATEGORY,
				"configurator_builder": "Simple", "default_billing_type": "Metered",
				"billable_unit": "1M tokens", "meter_kind": "Counter",
				"allowed_resource_types": [{"resource_type": "Tokens"}],
			}).insert(ignore_permissions=True)

	def tearDown(self):
		_cleanup()
		if frappe.db.exists("Plan Sub-Category", "Premium Tokens"):
			frappe.delete_doc("Plan Sub-Category", "Premium Tokens", force=True, ignore_permissions=True)

	def _cfg(self, template="Cfg Simple", simple_plans=None, **extra):
		return frappe.get_doc({
			"doctype": "Plan Configurator", "template_name": template,
			"category": self.CATEGORY, "billing_cycle": "Monthly", "is_active": 1,
			"base_rates": [{"currency": "USD", "base_rate": 10}],
			"simple_plans": simple_plans if simple_plans is not None else [
				{"title": "Tokens 10M", "resource_type": "Tokens", "quantity": 10, "unit": "1M tokens", "multiplier": 1},
				{"title": "Tokens 100M", "resource_type": "Tokens", "quantity": 100, "unit": "1M tokens", "multiplier": 10},
			],
			**extra,
		}).insert(ignore_permissions=True)

	def test_builder_dispatches_from_family(self):
		self.assertEqual(self._cfg().builder, "Simple")  # fetched from the category

	def test_authors_hash_named_priced_plans(self):
		cfg = self._cfg()
		out = cfg.generate_and_price()
		self.assertEqual(len(out["created"]), 2)
		cfg.reload()
		ten = frappe.get_doc("Plan", next(r.plan for r in cfg.simple_plans if r.title == "Tokens 10M"))
		self.assertNotEqual(ten.name, ten.title)  # opaque hash, not the title
		self.assertEqual(ten.category, self.CATEGORY)
		self.assertEqual(ten.title, "Tokens 10M")
		self.assertEqual([(i.resource_type, i.quantity) for i in ten.includes], [("Tokens", 10)])
		self.assertEqual(ten.get_rate("USD"), 10)  # base × 1 — no vCPU/disk anywhere
		hundred = frappe.get_doc("Plan", next(r.plan for r in cfg.simple_plans if r.title == "Tokens 100M"))
		self.assertEqual(hundred.get_rate("USD"), 100)  # base × 10

	def test_is_idempotent_via_rung_link(self):
		cfg = self._cfg()
		cfg.generate_and_price()
		out = cfg.generate_and_price()
		self.assertEqual(len(out["created"]), 0)
		self.assertEqual(len(out["skipped"]), 2)

	def test_off_family_resource_type_is_rejected(self):
		cfg = self._cfg(template="Cfg Simple Bad", simple_plans=[
			{"title": "Bad", "resource_type": "Disk", "quantity": 1, "unit": "GB", "multiplier": 1}])
		with self.assertRaises(frappe.ValidationError):
			cfg.generate_and_price()

	def test_custom_mints_sub_category_first(self):
		cfg = self._cfg(template="Cfg Simple Custom", new_sub_category="Premium Tokens")
		cfg.generate_and_price()
		self.assertEqual(
			frappe.db.get_value("Plan Sub-Category", "Premium Tokens", "category"), self.CATEGORY)
		cfg.reload()
		self.assertEqual(frappe.get_doc("Plan", cfg.simple_plans[0].plan).sub_category, "Premium Tokens")

	def test_no_sub_category_when_family_has_none(self):
		cfg = self._cfg(template="Cfg Simple NoSub")
		cfg.generate_and_price()
		cfg.reload()
		self.assertIsNone(frappe.get_doc("Plan", cfg.simple_plans[0].plan).sub_category)
