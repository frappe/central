# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Verb-first catalog Desk workspace + the Metered Add-ons report (ADR 0012, #88)."""

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.report.metered_add_ons.metered_add_ons import execute
from central.billing.tests.utils import make_metered_plan


class TestMeteredAddOnsReport(IntegrationTestCase):
	def test_add_on_shows_allowance_and_per_currency_overage_in_one_row(self):
		make_metered_plan(
			"addon-transfer-report",
			resource_type="Transfer",
			unit="GB",
			quantity=50,  # the included allowance
			rates=[
				{"cluster": "", "currency": "INR", "rate": 2},
				{"cluster": "", "currency": "USD", "rate": 0.03},
			],
		)
		columns, data = execute()
		fieldnames = {c["fieldname"] for c in columns}
		# Allowance + a column per currency the add-on is priced in.
		self.assertIn("allowance", fieldnames)
		self.assertIn("overage_inr", fieldnames)
		self.assertIn("overage_usd", fieldnames)

		row = next(r for r in data if r["plan"] == "addon-transfer-report")
		self.assertEqual(row["resource_type"], "Transfer")
		self.assertEqual(row["allowance"], 50)
		self.assertEqual(row["unit"], "GB")
		self.assertEqual(row["overage_inr"], 2)
		self.assertEqual(row["overage_usd"], 0.03)


class TestVerbFirstWorkspace(IntegrationTestCase):
	def setUp(self):
		self.ws = frappe.get_doc("Workspace", "Billing")
		self.content = frappe.parse_json(self.ws.content)

	def test_leads_with_verb_shortcuts_wired_to_the_configurator(self):
		by_label = {s.label: s for s in self.ws.shortcuts}
		for verb in ("Launch a plan", "Launch an add-on (metered)", "Update prices"):
			self.assertIn(verb, by_label)
			self.assertEqual(by_label[verb].link_to, "Plan Configurator")
		# Retire opens a filtered Plan list (deactivate), not the Configurator.
		self.assertIn("Retire a plan / add-on", by_label)

	def test_how_it_works_block_renders(self):
		paragraphs = [b for b in self.content if b["type"] == "paragraph"]
		self.assertTrue(any("How it works" in p["data"]["text"] for p in paragraphs))

	def test_metered_add_ons_report_is_surfaced(self):
		by_label = {s.label: s for s in self.ws.shortcuts}
		self.assertIn("Metered add-ons", by_label)
		self.assertEqual(by_label["Metered add-ons"].link_to, "Metered Add-ons")
		self.assertEqual(by_label["Metered add-ons"].type, "Report")

	def test_retired_doctypes_are_not_linked(self):
		linked = {l.link_to for l in self.ws.links if l.type == "Link"}
		self.assertNotIn("Price Lock", linked)
		self.assertNotIn("Trust Tier", linked)

	def test_masters_are_under_an_advanced_group(self):
		# Walk the Card Break groups; the catalog masters live under "Advanced".
		groups: dict[str, list[str]] = {}
		current = None
		for l in self.ws.links:
			if l.type == "Card Break":
				current = l.label
				groups[current] = []
			elif current:
				groups[current].append(l.link_to)
		advanced = next((items for label, items in groups.items() if "Advanced" in label), [])
		for master in ("Plan Category", "Plan Sub-Category", "Resource Type", "Catalog Rate"):
			self.assertIn(master, advanced)
