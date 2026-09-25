# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Tax — GST + SEZ; TDS withholding seam (issue #13)."""

import frappe

from central.billing.revenue import invoicing, tax
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	add_segment,
	complete_billing_profile,
	make_billing_subscription,
	make_plan,
)

TEAM = "team-tax"
CLUSTER = "ap-south-1"
PLAN = "bundle-tax-test"


def set_tax_profile(**kw):
	if frappe.db.exists("Tax Profile", TEAM):
		frappe.delete_doc("Tax Profile", TEAM, force=True)
	frappe.get_doc({"doctype": "Tax Profile", "team": TEAM, **kw}).insert(ignore_permissions=True)


class TaxTestBase(IntegrationTestCase):
	def setUp(self):
		make_plan(PLAN)
		self._purge()
		self.sub = make_billing_subscription(TEAM, CLUSTER, PLAN, billing_cycle="Monthly")
		add_segment(self.sub, "Created", 1000, "2026-06-01 00:00:00")  # full-month fixed line = 1000

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Invoice", {"team": TEAM})
		if frappe.db.exists("Tax Profile", TEAM):
			frappe.db.delete("Tax Profile", {"team": TEAM})
		for sub in frappe.get_all("Subscription", {"team": TEAM}, pluck="name"):
			frappe.db.delete("Subscription Change", {"subscription": sub})
			frappe.db.delete("Subscription", {"name": sub})
		frappe.db.commit()

	def _invoice(self):
		name = invoicing.generate_draft_invoice(self.sub, "2026-06-01", "2026-06-30")
		return frappe.get_doc("Invoice", name)


class TestOutputTax(TaxTestBase):
	def test_no_profile_is_untaxed(self):
		inv = self._invoice()
		self.assertEqual(inv.output_tax_type, "None")
		self.assertEqual(inv.output_tax_amount, 0)
		self.assertEqual(inv.total, 1000.0)
		self.assertEqual(inv.expected_collection, 1000.0)

	def test_gst_is_additive_to_total(self):
		set_tax_profile(output_tax_type="GST", output_tax_rate=18)
		inv = self._invoice()
		self.assertEqual(inv.output_tax_amount, 180.0)  # 18% of 1000
		self.assertEqual(inv.total, 1180.0)  # subtotal + output tax
		self.assertEqual(inv.expected_collection, 1180.0)  # charged the gross


class TestZeroRating(TaxTestBase):
	def test_sez_is_zero_with_a_reason_code(self):
		set_tax_profile(output_tax_type="GST", output_tax_rate=18, zero_rated=1, zero_rating_reason="SEZ")
		inv = self._invoice()
		self.assertEqual(inv.output_tax_amount, 0)  # zero-rated
		self.assertEqual(inv.zero_rating_reason, "SEZ")  # ... but with a reason
		self.assertEqual(inv.total, 1000.0)

	def test_zero_rated_profile_requires_a_reason(self):
		with self.assertRaises(frappe.ValidationError):
			set_tax_profile(output_tax_type="GST", zero_rated=1)  # no reason


class TestGstinStanding(TaxTestBase):
	GSTIN = "27AAPFU0939F1ZV"

	def _gstin(self, status):
		complete_billing_profile(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, {"gstin": self.GSTIN, "gst_status": status})

	def test_active_gstin_goes_on_the_invoice(self):
		self._gstin("Active")
		self.assertEqual(self._invoice().customer_gstin, self.GSTIN)

	def test_unchecked_gstin_is_trusted(self):
		self._gstin(None)
		self.assertEqual(self._invoice().customer_gstin, self.GSTIN)

	def test_lapsed_gstin_bills_as_unregistered(self):
		for status in ("Inactive", "Suspended", "Cancelled", "Invalid"):
			self._gstin(status)
			frappe.db.delete("Invoice", {"team": TEAM})
			set_tax_profile(output_tax_type="GST", output_tax_rate=18)
			inv = self._invoice()
			self.assertFalse(inv.customer_gstin, status)
			self.assertEqual(inv.output_tax_amount, 180.0)  # GST still charged

	def test_lapsed_sez_gstin_loses_zero_rating(self):
		self._gstin("Cancelled")
		set_tax_profile(output_tax_type="GST", output_tax_rate=18, zero_rated=1, zero_rating_reason="SEZ")
		inv = self._invoice()
		self.assertEqual(inv.output_tax_amount, 180.0)
		self.assertFalse(inv.zero_rating_reason)

	def test_lapsed_gstin_keeps_overseas_zero_rating(self):
		self._gstin("Cancelled")
		set_tax_profile(
			output_tax_type="GST", output_tax_rate=18, zero_rated=1, zero_rating_reason="Overseas"
		)
		self.assertEqual(self._invoice().output_tax_amount, 0)


class TestWithholdingSeam(TaxTestBase):
	def test_tds_reduces_collection_not_total(self):
		# GST 18% + TDS 10% (the seam — 0 at launch, exercised here).
		set_tax_profile(output_tax_type="GST", output_tax_rate=18, tds_applicable=1, tds_rate=10)
		inv = self._invoice()
		self.assertEqual(inv.total, 1180.0)  # gross unchanged by TDS
		self.assertEqual(inv.tds_amount, 100.0)  # 10% of the 1000 subtotal
		self.assertEqual(inv.expected_collection, 1080.0)  # total - tds

	def test_paid_state_defined_against_expected_collection(self):
		set_tax_profile(tds_applicable=1, tds_rate=10)
		inv = self._invoice()  # total 1000, tds 100, expected 900
		# A TDS customer legally short-pays the collected amount → still paid.
		inv.amount_paid = inv.expected_collection
		inv.tds_certificate_received = 1
		self.assertTrue(tax.is_paid(inv))

	def test_mandate_ceiling_uses_gross_total(self):
		set_tax_profile(tds_applicable=1, tds_rate=10)
		inv = self._invoice()
		# The mandate was authorised for the gross, not the TDS-reduced amount.
		self.assertEqual(tax.mandate_ceiling_amount(inv), inv.total)
		self.assertGreater(inv.total, inv.expected_collection)
