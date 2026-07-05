# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Provisioning when a team completes its billing profile: entry trust tier,
tax profile, and welcome credits (idempotent)."""

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase

from central.billing.api.dashboard import account
from central.billing.payments.provisioning import WELCOME_CREDITS
from central.billing.revenue import credits
from central.billing.tests.test_entitlements import make_ladder
from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.utils import ensure_team

TEAM = "team-prov"


class TestBillingProfileProvisioning(IntegrationTestCase):
	def setUp(self):
		make_ladder()  # t0 is the default entry tier, and prices INR
		ensure_team(TEAM)
		make_razorpay_gateway("GW-Prov-INR")  # makes INR a supported currency
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for dt in ("Credit Ledger Entry", "Credit Wallet", "Tax Profile", "Billing Profile"):
			frappe.db.delete(dt, {"team": TEAM})

	def _complete_profile(self, legal_name="Prov Ltd"):
		account.save_billing_profile(
			TEAM, currency="INR", legal_name=legal_name, address_line1="1 St",
			city="Pune", state="Maharashtra", country="India", pincode="411001",
		)

	def test_complete_profile_assigns_tier_tax_and_credits(self):
		self._complete_profile()

		# Entry trust tier linked (caps now resolve instead of being unbounded).
		profile = frappe.db.get_value(
			"Billing Profile", TEAM, ["trust_tier_level", "trust_tier"], as_dict=True
		)
		self.assertEqual(profile.trust_tier_level, "t0")
		self.assertEqual(profile.trust_tier, "t0")

		# India → a GST tax profile.
		tax = frappe.db.get_value(
			"Tax Profile", TEAM, ["output_tax_type", "output_tax_rate"], as_dict=True
		)
		self.assertEqual(tax.output_tax_type, "GST")
		self.assertEqual(tax.output_tax_rate, 18)

		# Welcome credits granted in the team's currency.
		self.assertEqual(credits.get_balance(TEAM)["balance"], WELCOME_CREDITS["INR"])

	def test_incomplete_profile_provisions_nothing(self):
		# currency + legal name only (no address) → not complete → no side effects.
		account.save_billing_profile(TEAM, currency="INR", legal_name="Prov Ltd")
		self.assertIsNone(frappe.db.get_value("Billing Profile", TEAM, "trust_tier_level"))
		self.assertFalse(frappe.db.exists("Tax Profile", TEAM))
		self.assertEqual(credits.get_balance(TEAM)["balance"], 0)

	def test_provisioning_is_idempotent(self):
		self._complete_profile()
		self._complete_profile(legal_name="Prov Ltd Renamed")

		self.assertEqual(credits.get_balance(TEAM)["balance"], WELCOME_CREDITS["INR"])
		self.assertEqual(
			frappe.db.count("Credit Ledger Entry", {"team": TEAM, "reference_type": "Promotion"}), 1
		)
		self.assertEqual(frappe.db.count("Tax Profile", {"team": TEAM}), 1)
