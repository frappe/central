# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The Plan Configurator authors the component rate card (ADR 0011, #87).

Covers: authoring a component card through the Configurator, capturing every shipped
currency in one place, the incomplete-card surfacing that fixes the `$0` estimate,
and the preset-vs-component divergence warning."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.catalog import component_card
from central.billing.catalog.pricing import resolve_component_rate, set_catalog_rate
from central.billing.tests.utils import make_plan

# A currency with no seeded starter card, so tests author it from scratch.
CUR = "JPY"


def _configurator(name):
	if frappe.db.exists("Plan Configurator", name):
		frappe.delete_doc("Plan Configurator", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Plan Configurator",
			"template_name": name,
			"category": "VM Plans",
			"plan_name_prefix": "Bundle",
			"start_vcpu": "1",
			"ceiling_vcpu": "1",
			"memory_ratio": "1:4",
			"base_rates": [{"currency": "INR", "base_rate": 100}],
		}
	).insert(ignore_permissions=True)


class TestComponentCardModule(IntegrationTestCase):
	def _clear(self):
		frappe.db.delete("Catalog Rate", {"priced_doctype": "Resource Type", "currency": CUR})
		frappe.db.commit()

	def setUp(self):
		self._clear()

	def tearDown(self):
		self._clear()

	def test_set_component_rate_writes_a_catalog_rate(self):
		component_card.set_component_rate("Compute", CUR, 100)
		self.assertEqual(resolve_component_rate("Compute", CUR), 100)

	def test_set_component_rate_rejects_unknown_resource_type(self):
		with self.assertRaises(frappe.ValidationError):
			component_card.set_component_rate("Nonsense", CUR, 100)

	def test_gaps_lists_unpriced_primitives(self):
		component_card.set_component_rate("Compute", CUR, 100)
		component_card.set_component_rate("Memory", CUR, 50)
		# Disk is still unpriced → an incomplete card for this currency.
		self.assertEqual(component_card.component_card_gaps(CUR), ["Disk"])
		self.assertFalse(component_card.is_component_card_complete(CUR))

	def test_complete_card_has_no_gaps(self):
		for rt, rate in (("Compute", 100), ("Memory", 50), ("Disk", 5)):
			component_card.set_component_rate(rt, CUR, rate)
		self.assertEqual(component_card.component_card_gaps(CUR), [])
		self.assertTrue(component_card.is_component_card_complete(CUR))

	def test_preset_below_component_sum_is_flagged_as_discount(self):
		# Component sum for 2·4·80 at 100/50/5 = 200 + 200 + 400 = 800.
		for rt, rate in (("Compute", 100), ("Memory", 50), ("Disk", 5)):
			component_card.set_component_rate(rt, CUR, rate)
		plan = make_plan("bundle-cc-below", rates=[{"cluster": "", "currency": CUR, "rate": 600}])
		warning = component_card.preset_component_warning(plan, CUR)
		self.assertEqual(warning["kind"], "below")
		self.assertEqual(warning["flat_rate"], 600)
		self.assertEqual(warning["component_sum"], 800)

	def test_preset_above_component_sum_is_flagged_as_mispricing(self):
		for rt, rate in (("Compute", 100), ("Memory", 50), ("Disk", 5)):
			component_card.set_component_rate(rt, CUR, rate)
		plan = make_plan("bundle-cc-above", rates=[{"cluster": "", "currency": CUR, "rate": 900}])
		self.assertEqual(component_card.preset_component_warning(plan, CUR)["kind"], "above")

	def test_preset_matching_component_sum_has_no_warning(self):
		for rt, rate in (("Compute", 100), ("Memory", 50), ("Disk", 5)):
			component_card.set_component_rate(rt, CUR, rate)
		plan = make_plan("bundle-cc-match", rates=[{"cluster": "", "currency": CUR, "rate": 800}])
		self.assertIsNone(component_card.preset_component_warning(plan, CUR))

	def test_incomplete_card_yields_no_false_warning(self):
		# Only Compute priced → the config can't be summed, so no misleading warning.
		component_card.set_component_rate("Compute", CUR, 100)
		plan = make_plan("bundle-cc-partial", rates=[{"cluster": "", "currency": CUR, "rate": 600}])
		self.assertIsNone(component_card.preset_component_warning(plan, CUR))


class TestConfiguratorAuthorsCard(IntegrationTestCase):
	def _clear(self):
		frappe.db.delete("Catalog Rate", {"priced_doctype": "Resource Type", "currency": CUR})
		frappe.db.commit()

	def setUp(self):
		self._clear()

	def tearDown(self):
		self._clear()

	def test_apply_component_card_writes_catalog_rates_and_reports_complete(self):
		doc = _configurator("cc-apply")
		for rt, rate in (("Compute", 100), ("Memory", 50), ("Disk", 5)):
			doc.append("component_rates", {"resource_type": rt, "currency": CUR, "rate": rate})
		doc.save(ignore_permissions=True)

		result = doc.apply_component_card()
		self.assertEqual(len(result["applied"]), 3)
		self.assertEqual(result["incomplete"], {})  # every currency complete
		self.assertEqual(resolve_component_rate("Compute", CUR), 100)

	def test_apply_component_card_surfaces_incomplete_currency(self):
		doc = _configurator("cc-incomplete")
		# Disk deliberately omitted for CUR → an incomplete card.
		for rt, rate in (("Compute", 100), ("Memory", 50)):
			doc.append("component_rates", {"resource_type": rt, "currency": CUR, "rate": rate})
		doc.save(ignore_permissions=True)

		result = doc.apply_component_card()
		self.assertEqual(result["incomplete"], {CUR: ["Disk"]})

	def test_seed_component_rows_captures_every_shipped_currency(self):
		doc = _configurator("cc-seed")
		with patch(
			"central.billing.gateways.registry.supported_currencies", return_value=["INR", "USD"]
		):
			out = doc.seed_component_rows()
		# 3 primitives × 2 currencies, none pre-existing.
		self.assertEqual(out["added"], 6)
		pairs = {(r.resource_type, r.currency) for r in doc.component_rates}
		self.assertIn(("Disk", "USD"), pairs)
		self.assertIn(("Compute", "INR"), pairs)

	def test_seed_is_idempotent(self):
		doc = _configurator("cc-seed-idem")
		with patch(
			"central.billing.gateways.registry.supported_currencies", return_value=["INR"]
		):
			doc.seed_component_rows()
			second = doc.seed_component_rows()
		self.assertEqual(second["added"], 0)  # already seeded, nothing added
		self.assertEqual(len(doc.component_rates), 3)


class TestComponentRateNotPublic(IntegrationTestCase):
	def test_update_component_rate_is_not_a_whitelisted_endpoint(self):
		# ADR 0011: the Configurator is the single authoring authority; there is no
		# parallel public component-rate endpoint.
		from central.billing.api.admin.catalog import update_component_rate

		self.assertNotIn(update_component_rate, frappe.whitelisted)
