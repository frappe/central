# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan Configurator authoring helper (issue #33).

Authoring-only convenience: pick a memory ratio (1:2 / 1:4) and vCPU, auto-fill
memory, add disk, and write PLAIN quantity/unit rows into Plan Includes. The
ratio is a pre-fill default, not a constraint (off-ratio overrides are allowed).
No schema change, no billing change — millicores/ratio never reach the data.
"""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import plans

PLAN = "bundle-configured-test"


class TestConfigureIncludes(IntegrationTestCase):
	def test_ratio_1_2_derives_memory(self):
		includes = plans.configure_includes(vcpu=0.125, ratio="1:2", disk_gb=10)
		by_type = {r["resource_type"]: r for r in includes}
		self.assertEqual(by_type["compute"]["quantity"], 0.125)
		self.assertEqual(by_type["compute"]["unit"], "vCPU")
		self.assertEqual(by_type["memory"]["quantity"], 0.25)  # 0.125 * 2
		self.assertEqual(by_type["memory"]["unit"], "GB")
		self.assertEqual(by_type["disk"]["quantity"], 10)

	def test_ratio_1_4_derives_high_memory(self):
		includes = plans.configure_includes(vcpu=1, ratio="1:4", disk_gb=40)
		memory = next(r for r in includes if r["resource_type"] == "memory")
		self.assertEqual(memory["quantity"], 4)  # 1 * 4

	def test_memory_override_is_off_ratio(self):
		# 1 vCPU + 3 GB is neither 1:2 nor 1:4 — the override must win.
		includes = plans.configure_includes(vcpu=1, ratio="1:2", disk_gb=20, memory_gb=3)
		memory = next(r for r in includes if r["resource_type"] == "memory")
		self.assertEqual(memory["quantity"], 3)


class TestCreateConfiguredPlan(IntegrationTestCase):
	def tearDown(self):
		if frappe.db.exists("Plan", PLAN):
			frappe.delete_doc("Plan", PLAN, force=True)

	def test_persists_plain_includes(self):
		plans.create_configured_plan(name=PLAN, title="Configured", vcpu=0.25, ratio="1:2", disk_gb=20)
		doc = frappe.get_doc("Plan", PLAN)
		by_type = {r.resource_type: r for r in doc.includes}
		self.assertEqual(by_type["compute"].quantity, 0.25)
		self.assertEqual(by_type["memory"].quantity, 0.5)  # 0.25 * 2
		self.assertEqual(by_type["disk"].quantity, 20)
		# Plain quantity/unit only — no millicores/ratio stored anywhere.
		self.assertEqual(by_type["compute"].unit, "vCPU")
