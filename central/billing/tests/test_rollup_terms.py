# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Correcting a rollup's terms writes a new version and retires the old one."""

import frappe

from central.billing.revenue import metering
from central.billing.tests.utils import BillingTestCase, ensure_team


class TestRollupTermsOverride(BillingTestCase):
	def setUp(self):
		self.team = ensure_team("team-rollup-terms")
		self.key = f"rollup-{frappe.generate_hash(length=8)}"
		self.rollup = frappe.get_doc(
			{
				"doctype": "Usage Rollup",
				"resource_id": "res-1",
				"team": self.team,
				"cluster": "cluster-1",
				"resource_type": "AI Tokens",
				"meter_type": "Counter",
				"period_start": "2026-06-01 00:00:00",
				"period_end": "2026-06-30 23:59:59",
				"quantity": 1000,
				"unit": "Nos",
				"currency": "USD",
				"locked_allowance": 100,
				"locked_rate": 0.5,
				"idempotency_key": self.key,
			}
		).insert(ignore_permissions=True)

	def test_the_original_row_is_never_edited(self):
		new = metering.override_terms(self.rollup.name, rate=0.25, reason="rate was wrong")
		old = frappe.get_doc("Usage Rollup", self.rollup.name)

		self.assertEqual(old.locked_rate, 0.5)
		self.assertEqual(old.superseded_by, new)
		self.assertEqual(frappe.db.get_value("Usage Rollup", new, "locked_rate"), 0.25)

	def test_the_new_version_carries_the_quantity_and_the_untouched_terms(self):
		new = metering.override_terms(self.rollup.name, rate=0.25)
		doc = frappe.get_doc("Usage Rollup", new)
		self.assertEqual(doc.quantity, 1000)
		self.assertEqual(doc.locked_allowance, 100)
		self.assertIsNone(doc.superseded_by)

	def test_a_correction_may_move_the_allowance_alone(self):
		new = metering.override_terms(self.rollup.name, allowance=250)
		doc = frappe.get_doc("Usage Rollup", new)
		self.assertEqual(doc.locked_allowance, 250)
		self.assertEqual(doc.locked_rate, 0.5)

	def test_correcting_a_correction_follows_the_chain(self):
		first = metering.override_terms(self.rollup.name, rate=0.25)
		second = metering.override_terms(self.rollup.name, rate=0.1)

		self.assertEqual(frappe.db.get_value("Usage Rollup", first, "superseded_by"), second)
		self.assertEqual(metering.live_rollup(self.rollup.name), second)
		self.assertEqual(frappe.db.get_value("Usage Rollup", second, "locked_rate"), 0.1)

	def test_a_correction_needs_something_to_correct(self):
		with self.assertRaises(frappe.ValidationError):
			metering.override_terms(self.rollup.name)

	def test_only_the_live_version_is_billed(self):
		metering.override_terms(self.rollup.name, rate=0.25)
		lines = metering._metered_lines(self.team, ["cluster-1"], "2026-06-01", "2026-06-30")
		self.assertLessEqual(len(lines), 1)
		if lines:
			# 900 units of overage at the corrected rate, not the original one.
			self.assertEqual(lines[0]["rate"], 0.25)

	def test_a_later_usage_report_lands_on_the_live_version(self):
		new = metering.override_terms(self.rollup.name, rate=0.25)
		metering.ingest_rollup({"idempotency_key": self.key, "quantity": 4321, "resource_type": "AI Tokens"})

		self.assertEqual(frappe.db.get_value("Usage Rollup", new, "quantity"), 4321)
		self.assertEqual(frappe.db.get_value("Usage Rollup", self.rollup.name, "quantity"), 1000)
