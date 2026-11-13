# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""A mandate covers a bill at the trust-tier cap, GST included."""

import frappe

from central.billing.catalog.entitlements import recompute_trust_tier
from central.billing.payments import mandates, payments
from central.billing.tests.test_entitlements import make_ladder
from central.billing.tests.test_mandates import CALLBACK, GATEWAY, make_gateway, stub_adapter
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import (
	clear_team_tier,
	complete_billing_profile,
	ensure_team,
	set_team_tier,
)

TEAM = "team-mandate-gst"


def set_gst(rate=18, **kw):
	frappe.db.set_value("Tax Profile", TEAM, {"output_tax_rate": rate, "zero_rated": 0, **kw})


class MandateGstTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_ladder()
		make_gateway()
		for name in frappe.get_all("Payment Method", filters={"team": TEAM}, pluck="name"):
			frappe.delete_doc("Payment Method", name, force=True)
		frappe.db.delete("Gateway Customer", {"team": TEAM})
		complete_billing_profile(TEAM)
		clear_team_tier(TEAM)
		set_gst(18)


class TestMandateCeiling(MandateGstTestBase):
	def test_a_cap_below_the_silent_ceiling_gets_its_gst(self):
		set_team_tier(TEAM, level="t0", max_spend=6000)
		self.assertEqual(payments.mandate_ceiling(TEAM, GATEWAY, "INR"), 7080.0)

	def test_the_silent_ceiling_still_binds(self):
		set_team_tier(TEAM, level="t0", max_spend=14000)
		self.assertEqual(payments.mandate_ceiling(TEAM, GATEWAY, "INR"), 15000.0)

	def test_a_zero_rated_sez_team_has_no_gst_on_top(self):
		set_gst(18, zero_rated=1, zero_rating_reason="SEZ")
		set_team_tier(TEAM, level="t0", max_spend=6000)
		self.assertEqual(payments.mandate_ceiling(TEAM, GATEWAY, "INR"), 6000.0)

	def test_a_lapsed_sez_gstin_pays_gst_so_the_ceiling_includes_it(self):
		set_gst(18, zero_rated=1, zero_rating_reason="SEZ")
		frappe.db.set_value("Billing Profile", TEAM, {"gstin": "27AABCT1111T1Z5", "gst_status": "Cancelled"})
		set_team_tier(TEAM, level="t0", max_spend=6000)
		self.assertEqual(payments.mandate_ceiling(TEAM, GATEWAY, "INR"), 7080.0)


class TestUpiMandate(MandateGstTestBase):
	def _active_mandate(self):
		with stub_adapter(signature_ok=True):
			result = mandates.setup_mandate(TEAM, GATEWAY, customer_id="cust_x")
			mandates.confirm_mandate(result["payment_method"], CALLBACK)
		return result["payment_method"]

	def test_setup_registers_the_cap_with_gst(self):
		recompute_trust_tier(TEAM, paid_invoice_count=0, cumulative_paid=0)  # t0 cap = 100
		with stub_adapter() as adapter:
			result = mandates.setup_mandate(TEAM, GATEWAY, customer_id="cust_x")
		self.assertEqual(adapter.setup_payment_method.call_args.args[1]["max_amount"], 118.0)
		self.assertEqual(
			frappe.db.get_value("Payment Method", result["payment_method"], "mandate_max_amount"), 118
		)

	def test_a_mandate_registered_without_gst_is_re_authorised(self):
		recompute_trust_tier(TEAM, paid_invoice_count=0, cumulative_paid=0)
		pm = self._active_mandate()
		frappe.db.set_value("Payment Method", pm, "mandate_max_amount", 100)  # the pre-GST ceiling
		self.assertEqual(mandates.reconcile_mandates_to_cap(TEAM), [pm])

	def test_a_mandate_with_gst_needs_no_re_authorisation(self):
		recompute_trust_tier(TEAM, paid_invoice_count=0, cumulative_paid=0)
		pm = self._active_mandate()
		self.assertEqual(mandates.reconcile_mandates_to_cap(TEAM), [])
		self.assertFalse(frappe.db.get_value("Payment Method", pm, "reauth_required"))

	def test_upi_is_refused_when_the_cap_with_gst_reaches_the_recurring_limit(self):
		set_team_tier(TEAM, level="t0", max_spend=90000)  # 1,06,200 with GST
		elig = mandates.upi_eligibility(TEAM)
		self.assertFalse(elig["eligible"])
		self.assertEqual(elig["cap"], 106200.0)

	def test_upi_is_allowed_below_the_recurring_limit_with_gst(self):
		set_team_tier(TEAM, level="t0", max_spend=80000)  # 94,400 with GST
		self.assertTrue(mandates.upi_eligibility(TEAM)["eligible"])
