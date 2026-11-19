# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The patch clears the old INR default only from cards that hold no mandate."""

import frappe

from central.billing.tests.test_mandates import make_gateway
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, ensure_team
from central.patches.v0_0 import clear_default_mandate_currency

TEAM = "team-mandate-currency"


def make_method(gateway: str, method_type: str = "Card", ceiling: float = 0) -> str:
	# Seeding fixture rows for the patch, not acting as a user.
	return (
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": gateway,
				"method_type": method_type,
				"status": "Active",
				"mandate_currency": "INR",
				"mandate_max_amount": ceiling,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestClearDefaultMandateCurrency(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_gateway()
		make_stripe_gateway()

	def test_a_card_with_no_mandate_loses_the_default_currency(self):
		card = make_method("Stripe")
		clear_default_mandate_currency.execute()
		self.assertIsNone(frappe.db.get_value("Payment Method", card, "mandate_currency"))

	def test_a_card_with_a_mandate_keeps_its_currency(self):
		card = make_method("Stripe", ceiling=15000)
		clear_default_mandate_currency.execute()
		self.assertEqual(frappe.db.get_value("Payment Method", card, "mandate_currency"), "INR")

	def test_razorpay_mandates_keep_their_currency_with_no_ceiling(self):
		card = make_method("Razorpay")
		upi = make_method("Razorpay", method_type="UPI Autopay")
		clear_default_mandate_currency.execute()
		for method in (card, upi):
			self.assertEqual(frappe.db.get_value("Payment Method", method, "mandate_currency"), "INR")
