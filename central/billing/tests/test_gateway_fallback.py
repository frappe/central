# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Falling back to the other rail after a terminal decline (ADR 0022, #109).

The rule that matters here is the one that is not about UX: an ambiguous failure
must never produce a second charge. A timeout may still settle at the gateway, and
charging the other rail on top of it pays one invoice twice.
"""

import frappe

from central.billing.payments import decline
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import complete_billing_profile, ensure_team

TEAM = "team-fallback-rail"


class TestWhichDeclinesAreFinal(IntegrationTestCase):
	def test_a_refused_card_is_final(self):
		self.assertTrue(decline.is_terminal("card_declined"))
		self.assertTrue(decline.is_terminal("card_not_supported"))
		self.assertTrue(decline.is_terminal("authentication_failed"))

	def test_an_unfinished_charge_is_not(self):
		self.assertFalse(decline.is_terminal("processing"))
		self.assertFalse(decline.is_terminal("gateway_timeout"))
		self.assertFalse(decline.is_terminal("authentication_abandoned"))

	def test_a_code_we_do_not_recognise_is_treated_as_unfinished(self):
		"""The safe reading of "we don't know what happened" is "don't charge again"."""
		self.assertFalse(decline.is_terminal("some_new_stripe_code"))
		self.assertFalse(decline.is_terminal(None))


class TestTheOffer(IntegrationTestCase):
	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		make_razorpay_gateway([("INR", 1)])
		frappe.db.set_single_value("Billing Settings", "enable_gateway_fallback", 1)
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Attempt", {"team": TEAM})

	def _invoice_with_attempt(self, status="Failed", failure_code="card_declined"):
		inv = (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-06-01",
					"period_end": "2026-06-30",
					"currency": "INR",
					"subtotal": 5000,
					"total": 5000,
					"expected_collection": 5000,
					"items": [{"resource_type": "bundle", "plan": "p", "rate": 5000, "days": 30, "amount": 5000}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		attempt = frappe.get_doc(
			{
				"doctype": "Payment Attempt",
				"invoice": inv,
				"team": TEAM,
				"gateway": "Stripe",
				"amount": 5000,
				"currency": "INR",
				"status": "Initiated",
				"initiated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Payment Attempt", attempt.name, {"status": status, "failure_code": failure_code}
		)
		return inv

	def test_a_refused_stripe_card_offers_razorpay_with_the_amount_filled_in(self):
		from central.billing.api.dashboard import invoices

		inv = self._invoice_with_attempt()
		out = invoices.get_fallback_offer(inv)
		self.assertIsNotNone(out["offer"])
		self.assertEqual(out["offer"]["adapter_key"], "Razorpay")
		self.assertEqual(out["amount"], 5000.0)

	def test_a_timeout_offers_nothing(self):
		from central.billing.api.dashboard import invoices

		inv = self._invoice_with_attempt(failure_code="gateway_timeout")
		self.assertIsNone(invoices.get_fallback_offer(inv)["offer"])

	def test_nothing_is_offered_when_the_switch_is_off(self):
		from central.billing.api.dashboard import invoices

		frappe.db.set_single_value("Billing Settings", "enable_gateway_fallback", 0)
		inv = self._invoice_with_attempt()
		self.assertIsNone(invoices.get_fallback_offer(inv)["offer"])
