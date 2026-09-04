# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Verb-first catalog Desk workspace + the Metered Add-ons report (ADR 0012, #88)."""

import frappe

from central.billing.report.metered_add_ons.metered_add_ons import execute
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
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

	def test_catalog_guidance_block_renders(self):
		paragraphs = [b for b in self.content if b["type"] == "paragraph"]
		self.assertTrue(any("Plan Configurator" in p["data"]["text"] for p in paragraphs))

	def test_page_carries_no_link_cards(self):
		# Navigation lives in the sidebar; the workspace page is a dashboard, not a link farm.
		self.assertEqual(self.ws.links, [])
		self.assertFalse([b for b in self.content if b["type"] == "card"])


class TestBillingSidebar(IntegrationTestCase):
	"""The Workspace Sidebar is the navigation surface (Frappe v17)."""

	def setUp(self):
		self.sidebar = frappe.get_doc("Workspace Sidebar", "Billing")

	def sections(self) -> dict[str, list[str]]:
		"""Group the sidebar's child items under the Section Break they hang off."""
		groups: dict[str, list[str]] = {}
		current = None
		for item in self.sidebar.items:
			if item.type == "Section Break":
				current = item.label
				groups[current] = []
			elif current and item.child:
				groups[current].append(item.link_to)
		return groups

	def test_is_shipped_by_the_app_not_auto_generated(self):
		# An auto-generated sidebar just copies the workspace shortcuts, so the three
		# Configurator verbs show up as three identical links. This one is authored.
		self.assertTrue(self.sidebar.standard)
		self.assertEqual(self.sidebar.app, "central")

	def test_opens_with_home_and_the_configurator(self):
		first_three = [(i.label, i.link_type, i.link_to) for i in self.sidebar.items[:3]]
		self.assertEqual(
			first_three,
			[
				("Home", "Workspace", "Billing"),
				("Plan Configurator", "DocType", "Plan Configurator"),
				("Billing Simulator", "Page", "billing-simulator"),
			],
		)

	def test_every_top_level_item_is_distinct_and_carries_an_icon(self):
		top_level = [i for i in self.sidebar.items if not i.child]
		targets = [i.link_to for i in top_level if i.type == "Link"]
		self.assertEqual(len(targets), len(set(targets)), "duplicate top-level destinations")
		for item in top_level:
			self.assertTrue(item.icon, f"{item.label} has no icon")

	def test_sections_are_collapsible_and_their_items_nest(self):
		for item in self.sidebar.items:
			if item.type == "Section Break":
				self.assertTrue(item.indent, f"{item.label} must indent to render collapsible")
				self.assertTrue(item.collapsible)
		self.assertTrue(all(self.sections().values()), "a section has no items under it")

	def test_masters_are_grouped_under_catalog(self):
		for master in ("Plan Category", "Plan Sub-Category", "Resource Type", "Catalog Rate"):
			self.assertIn(master, self.sections()["Catalog"])

	def test_every_billing_report_is_reachable(self):
		linked = {i.link_to for i in self.sidebar.items if i.link_type == "Report"}
		shipped = set(frappe.get_all("Report", filters={"module": "Billing"}, pluck="name"))
		self.assertEqual(shipped - linked, set(), "reports missing from the sidebar")

	def test_retired_doctypes_are_not_linked(self):
		linked = {i.link_to for i in self.sidebar.items if i.type == "Link"}
		self.assertNotIn("Price Lock", linked)
		self.assertNotIn("Trust Tier", linked)
