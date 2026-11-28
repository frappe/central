# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Correcting a rollup's terms writes a new version and retires the old one."""

import frappe

from central.billing.revenue import metering, rollup_updates
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
		new = rollup_updates.override_terms(self.rollup.name, rate=0.25, reason="rate was wrong")
		old = frappe.get_doc("Usage Rollup", self.rollup.name)

		self.assertEqual(old.locked_rate, 0.5)
		self.assertEqual(old.superseded_by, new)
		self.assertEqual(frappe.db.get_value("Usage Rollup", new, "locked_rate"), 0.25)

	def test_the_new_version_carries_the_quantity_and_the_untouched_terms(self):
		new = rollup_updates.override_terms(self.rollup.name, rate=0.25)
		doc = frappe.get_doc("Usage Rollup", new)
		self.assertEqual(doc.quantity, 1000)
		self.assertEqual(doc.locked_allowance, 100)
		self.assertIsNone(doc.superseded_by)

	def test_a_correction_may_move_the_allowance_alone(self):
		new = rollup_updates.override_terms(self.rollup.name, allowance=250)
		doc = frappe.get_doc("Usage Rollup", new)
		self.assertEqual(doc.locked_allowance, 250)
		self.assertEqual(doc.locked_rate, 0.5)

	def test_correcting_a_correction_follows_the_chain(self):
		first = rollup_updates.override_terms(self.rollup.name, rate=0.25)
		second = rollup_updates.override_terms(self.rollup.name, rate=0.1)

		self.assertEqual(frappe.db.get_value("Usage Rollup", first, "superseded_by"), second)
		self.assertEqual(rollup_updates.live_rollup(self.rollup.name), second)
		self.assertEqual(frappe.db.get_value("Usage Rollup", second, "locked_rate"), 0.1)

	def test_a_correction_needs_something_to_correct(self):
		with self.assertRaises(frappe.ValidationError):
			rollup_updates.override_terms(self.rollup.name)

	def test_only_the_live_version_is_billed(self):
		rollup_updates.override_terms(self.rollup.name, rate=0.25)
		lines = metering._metered_lines(self.team, ["cluster-1"], "2026-06-01", "2026-06-30")
		self.assertLessEqual(len(lines), 1)
		if lines:
			# 900 units of overage at the corrected rate, not the original one.
			self.assertEqual(lines[0]["rate"], 0.25)

	def test_a_later_usage_report_lands_on_the_live_version(self):
		new = rollup_updates.override_terms(self.rollup.name, rate=0.25)
		metering.ingest_rollup({"idempotency_key": self.key, "quantity": 4321, "resource_type": "AI Tokens"})

		self.assertEqual(frappe.db.get_value("Usage Rollup", new, "quantity"), 4321)
		self.assertEqual(frappe.db.get_value("Usage Rollup", self.rollup.name, "quantity"), 1000)


class TestConvertedRollupTerms(BillingTestCase):
	def setUp(self):
		self.team = ensure_team("team-rollup-terms")
		self.key = f"rollup-{frappe.generate_hash(length=8)}"

	def report(self, rate: float, rate_date: str | None):
		terms = frappe._dict(
			team=self.team,
			cluster=None,
			currency="INR",
			allowance=0,
			rate=rate,
			rate_date=rate_date,
			is_converted=True,
		)
		metering.ingest_rollup(
			{
				"idempotency_key": self.key,
				"resource_id": "subject-1",
				"quantity": 2,
				"resource_type": "AI Usage",
				"locked_terms": terms,
			}
		)
		return frappe.db.get_value(
			"Usage Rollup", {"idempotency_key": self.key}, ["locked_rate", "rate_date"], as_dict=True
		)

	def test_a_converted_rollup_is_re_rated_until_its_rate_date_is_set(self):
		self.assertEqual(self.report(83.5, None), {"locked_rate": 83.5, "rate_date": None})
		locked = self.report(84.1, "2026-06-01")
		self.assertEqual((locked.locked_rate, str(locked.rate_date)), (84.1, "2026-06-01"))
		self.assertEqual(self.report(90, "2026-06-01").locked_rate, 84.1)

	def test_the_first_report_stamps_the_rate_and_its_date_together(self):
		locked = self.report(84.1, "2026-06-01")
		self.assertEqual((locked.locked_rate, str(locked.rate_date)), (84.1, "2026-06-01"))
		self.assertEqual(self.report(90, "2026-07-01").locked_rate, 84.1)


class TestUsageMonthTerms(BillingTestCase):
	def setUp(self):
		self.team = ensure_team("team-rollup-terms")
		self.month = frappe.get_doc(
			{
				"doctype": "Usage Month",
				"service": "storage",
				"meter": "bytes_stored",
				"subject": "res-1",
				"dimension": "",
				"month": "2026-06-01",
				"aggregation": "Level",
				"team": self.team,
				"subscription": "subscription-1",
				"resource_type": "Storage",
				"resource_id": "res-1",
				"cluster": "cluster-1",
				"quantity": 1000,
				"currency": "USD",
				"locked_allowance": 100,
				"locked_rate": 0.5,
				"counted_at": "2026-06-30 00:00:00",
			}
		)
		self.month.db_insert()

	def test_a_month_is_re_priced_in_place_with_its_old_terms_on_record(self):
		name = rollup_updates.correct_terms(self.month.name, rate=0.25, reason="rate was wrong")
		month = frappe.get_doc("Usage Month", name)
		self.assertEqual((name, month.locked_rate, month.locked_allowance), (self.month.name, 0.25, 100))
		self.assertFalse(month.terms_corrected)
		comment = frappe.db.get_value(
			"Comment", {"reference_doctype": "Usage Month", "reference_name": name}, "content"
		)
		self.assertIn("rate 0.5 to 0.25", comment)
		self.assertIn("rate was wrong", comment)

	def test_a_corrected_allowance_is_marked_so_a_recount_keeps_it(self):
		rollup_updates.correct_terms(self.month.name, allowance=250)
		month = frappe.get_doc("Usage Month", self.month.name)
		self.assertEqual((month.locked_allowance, month.terms_corrected), (250, 1))
