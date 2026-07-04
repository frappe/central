# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Consumer-service metered billing (ADR 0015): per-family settlement + reporting
mode, synthesized team-level subjects, dual-mode usage ingestion, and the
pilot-authenticated service API."""

import frappe
from frappe.tests import IntegrationTestCase


class TestPlanCategoryModes(IntegrationTestCase):
	"""settlement_mode / reporting_mode are per-family properties, blank resolving to
	the built default; both are meaningless on a Fixed family (ADR 0015)."""

	def _category(self, name, billing_type="Metered", **kwargs):
		if frappe.db.exists("Plan Category", name):
			frappe.delete_doc("Plan Category", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "Plan Category", "category_name": name, "billing_type": billing_type, **kwargs}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_blank_modes_resolve_to_built_defaults(self):
		cat = self._category("SM Metered Blank")
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")

	def test_explicit_modes_are_honoured(self):
		cat = self._category(
			"SM Prepaid Incremental",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		self.assertEqual(cat.effective_settlement_mode, "Prepaid Pack")
		self.assertEqual(cat.effective_reporting_mode, "Incremental")

	def test_modes_cleared_on_fixed_family(self):
		cat = self._category(
			"SM Fixed Bundle",
			billing_type="Fixed",
			settlement_mode="Prepaid Pack",
			reporting_mode="Incremental",
		)
		# A bundle has no metered reporting — the controller blanks both on validate.
		self.assertFalse(cat.settlement_mode)
		self.assertFalse(cat.reporting_mode)
		self.assertEqual(cat.effective_settlement_mode, "Postpaid Overage")
		self.assertEqual(cat.effective_reporting_mode, "Authoritative")
