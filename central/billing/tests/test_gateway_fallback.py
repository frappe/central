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


class TestMandateFailuresAreNotCardDeclines(IntegrationTestCase):
	"""Stripe's India mandate errors mean the standing permission is gone, not that
	the card is bad (ADR 0023)."""

	def test_the_mandate_codes_are_recognised(self):
		self.assertTrue(decline.is_mandate_failure("payment_intent_mandate_invalid"))
		self.assertTrue(decline.is_mandate_failure("india_recurring_payment_mandate_canceled"))
		self.assertTrue(decline.is_mandate_failure("transaction_not_approved"))
		self.assertFalse(decline.is_mandate_failure("card_declined"))

	def test_a_mandate_failure_is_final_for_that_method(self):
		"""Retrying the same method cannot work, so it must not read as ambiguous."""
		self.assertTrue(decline.is_terminal("india_recurring_payment_mandate_canceled"))


class TestTheGatewaysOwnHold(IntegrationTestCase):
	"""Stripe holds an India mandate charge in `processing` for 26 hours by design.
	It has not failed, and it is not stuck."""

	def test_reconciliation_leaves_a_held_attempt_alone(self):
		from central.billing.payments import reconciliation
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		invoice = (
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
				"invoice": invoice,
				"team": TEAM,
				"gateway": "Stripe",
				"amount": 5000,
				"currency": "INR",
				"status": "Initiated",
				"initiated_at": "2026-06-10 09:00:00",
				"gateway_transaction_id": "pi_held",
				"gateway_hold_until": "2026-06-11 11:00:00",
			}
		).insert(ignore_permissions=True)
		out = reconciliation.reconcile_attempt(attempt.name, now="2026-06-11 09:00:00")
		self.assertEqual(out["skipped"], "gateway_hold")

	def test_the_hold_is_read_off_the_intent_not_a_clock_of_ours(self):
		from central.billing.gateways.stripe_adapter import _predebit_hold

		intent = {
			"status": "processing",
			"processing": {
				"type": "card",
				"card": {"customer_notification": {"approval_requested": True, "completes_at": 1780000000}},
			},
		}
		self.assertIsNotNone(_predebit_hold(intent))
		self.assertIsNone(_predebit_hold({"status": "succeeded"}))


class TestOneInvoiceIsNeverChargedTwiceAcrossRails(IntegrationTestCase):
	"""A team holding a card on one rail and a mandate on the other.

	Rotating between them is the point of the ordered method list, but it must only
	happen when the first attempt is genuinely over. An ambiguous failure may still
	settle at the gateway, so charging the second rail on top of it takes the money
	twice for one invoice — the failure mode this whole rule exists to prevent.
	"""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		make_razorpay_gateway([("INR", 1)])
		frappe.db.set_single_value("Billing Settings", "enable_gateway_fallback", 1)
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		self.stripe_method = self._method("Stripe", "pm_stripe", priority=0)
		self.razorpay_method = self._method("Razorpay", "tok_rzp", priority=1)
		self.invoice = self._invoice()

	def _method(self, gateway, handle, priority):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": gateway,
					"method_type": "Card",
					"status": "Active",
					"gateway_method_id": handle,
					"gateway_customer_id": f"cus_{gateway.lower()}",
					"display_label": f"{gateway} card",
					"priority": priority,
					"validated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _invoice(self):
		return (
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

	def _charged_gateways(self):
		return frappe.get_all("Payment Attempt", filters={"invoice": self.invoice}, pluck="gateway")

	def test_an_ambiguous_failure_stops_instead_of_trying_the_other_rail(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection

		adapter = MagicMock()
		adapter.charge.return_value = PaymentResult(
			success=False,
			status="Failed",
			failure_code="processing_error",
			failure_reason="try again later",
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			out = collection.collect_invoice(self.invoice)

		self.assertEqual(out["reason"], "ambiguous_failure")
		self.assertEqual(adapter.charge.call_count, 1)
		self.assertEqual(self._charged_gateways(), ["Stripe"])

	def test_a_terminal_decline_does_rotate_to_the_other_rail(self):
		"""The counterpart: when the card really is refused, the second rail is tried
		exactly once, so the guard above isn't just blocking everything."""
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection

		adapter = MagicMock()
		adapter.charge.return_value = PaymentResult(
			success=False, status="Failed", failure_code="card_declined", failure_reason="declined"
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_invoice(self.invoice)

		self.assertEqual(sorted(self._charged_gateways()), ["Razorpay", "Stripe"])
		# Each method at most once per invoice — escalate, don't repeat.
		self.assertEqual(len(self._charged_gateways()), 2)

	def test_running_out_of_rails_asks_for_another_way_to_pay(self):
		from unittest.mock import MagicMock, patch

		from central.billing.gateways.base import PaymentResult
		from central.billing.payments import collection

		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		adapter = MagicMock()
		adapter.charge.return_value = PaymentResult(
			success=False, status="Failed", failure_code="card_declined", failure_reason="declined"
		)
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			collection.collect_invoice(self.invoice)

		self.assertTrue(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Add Payment Method"}
			)
		)

	def test_nothing_is_asked_of_a_team_that_never_had_a_method(self):
		"""Nothing was tried, so there is nothing to report — onboarding and the
		Action Required banner already carry that conversation."""
		from central.billing.payments import collection

		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		frappe.db.set_value("Payment Method", self.stripe_method, "status", "Cancelled")
		frappe.db.set_value("Payment Method", self.razorpay_method, "status", "Cancelled")

		out = collection.collect_invoice(self.invoice)

		self.assertEqual(out["reason"], "no_method")
		self.assertFalse(
			frappe.db.exists(
				"Billing Notification Log", {"team": TEAM, "event_type": "Add Payment Method"}
			)
		)


class TestWhereAMethodSaysItCameFrom(IntegrationTestCase):
	"""`fallback_reason` feeds the report that judges one rail against the other, so
	"my card was declined" is checked rather than believed."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		make_razorpay_gateway([("INR", 1)])
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.set_value("Billing Profile", TEAM, "phone", "9800000000")

	def _failed_attempt(self, failure_code):
		invoice = (
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
				"invoice": invoice,
				"team": TEAM,
				"gateway": "Stripe",
				"amount": 5000,
				"currency": "INR",
				"status": "Initiated",
				"initiated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Payment Attempt", attempt.name, {"status": "Failed", "failure_code": failure_code}
		)

	def _add(self, after_decline):
		from central.billing.api.dashboard import methods

		out = methods.setup_payment_method_order(
			TEAM, instrument="RuPay Card", after_decline=after_decline
		)
		return frappe.get_doc("Payment Method", out["payment_method"])

	def test_a_real_decline_is_recorded_as_one(self):
		self._failed_attempt("card_declined")
		self.assertEqual(self._add(after_decline=True).fallback_reason, "Stripe Decline")

	def test_an_unbacked_claim_is_not(self):
		"""Nothing was declined, so the method records the reason its own tile gives."""
		self.assertEqual(self._add(after_decline=True).fallback_reason, "Network Unsupported")

	def test_a_timeout_is_not_a_decline(self):
		self._failed_attempt("gateway_timeout")
		self.assertEqual(self._add(after_decline=True).fallback_reason, "Network Unsupported")

	def test_a_revoked_mandate_is_not_a_decline_either(self):
		"""The card was never refused — the standing permission went away."""
		self._failed_attempt("india_recurring_payment_mandate_canceled")
		self.assertEqual(self._add(after_decline=True).fallback_reason, "Network Unsupported")
