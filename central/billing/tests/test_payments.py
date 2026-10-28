# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Card Payment Method lifecycle (issue #05)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from central.billing.gateways.base import PaymentResult
from central.billing.payments import payments
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-cards"
GATEWAY = "Stripe"


def saved_card(**fields):
	"""What the gateway reports a setup saved."""
	return {
		"payment_method": f"pm_{frappe.generate_hash(length=6)}",
		"customer": "cus_created",
		"brand": "Visa",
		"last4": "4242",
		"exp_month": 12,
		"exp_year": 2030,
		**fields,
	}


def card_check(success: bool) -> PaymentResult:
	"""What the gateway answers to a card check."""
	if success:
		return PaymentResult(success=True, status="Validated")
	return PaymentResult(
		success=False,
		status="Failed",
		failure_code="card_declined",
		decline_code="insufficient_funds",
		failure_reason="Your card has insufficient funds.",
	)


@contextmanager
def stub_adapter(validate=True, card=None):
	"""Resolve a mock GatewayAdapter (no SDK touched)."""
	adapter = MagicMock()
	adapter.read_saved_card.return_value = card or saved_card()
	adapter.setup_payment_method.return_value = {
		"client_secret": "seti_secret_123",
		"setup_intent_id": "seti_123",
	}
	adapter.validate_payment_method.return_value = card_check(validate)
	adapter.create_customer.return_value = "cus_created"
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class CardTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_stripe_gateway()
		for name in frappe.get_all("Payment Method", filters={"team": TEAM}, pluck="name"):
			frappe.delete_doc("Payment Method", name, force=True)
		frappe.db.delete("Gateway Customer", {"team": TEAM})

	def add_active_card(self, last4="4242", expiry_month=12, expiry_year=2030):
		card = saved_card(last4=last4, exp_month=expiry_month, exp_year=expiry_year)
		with stub_adapter(validate=True, card=card):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			payments.confirm_payment_method(setup["payment_method"])
		return setup["payment_method"]


class TestSetupAndConfirm(CardTestBase):
	def test_initiate_returns_client_secret_and_pending_method(self):
		with stub_adapter():
			result = payments.initiate_payment_method_setup(TEAM, GATEWAY)
		self.assertEqual(result["client_secret"], "seti_secret_123")
		method = frappe.get_doc("Payment Method", result["payment_method"])
		self.assertEqual(method.method_type, "Card")
		self.assertEqual(method.status, "Pending Validation")
		self.assertEqual(method.setup_reference, "seti_123")

	def test_confirm_with_successful_microcharge_activates(self):
		with stub_adapter(validate=True, card=saved_card(payment_method="pm_live")) as adapter:
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"])
		adapter.read_saved_card.assert_called_once_with("seti_123")  # read by our stored setup
		adapter.validate_payment_method.assert_called_once()  # micro-charge ran
		self.assertEqual(method.status, "Active")
		self.assertEqual(method.gateway_method_id, "pm_live")
		self.assertEqual(method.display_label, "Visa ···· 4242")
		self.assertTrue(method.validated_at)
		self.assertTrue(method.is_default)  # first active method becomes default

	def test_failed_microcharge_leaves_method_failed(self):
		with stub_adapter(validate=False):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"])
		self.assertEqual(method.status, "Failed")
		self.assertFalse(method.is_default)

	def test_a_failed_card_check_keeps_the_gateway_reason(self):
		with stub_adapter(validate=False):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"])

		self.assertEqual((method.failure_code, method.decline_code), ("card_declined", "insufficient_funds"))
		self.assertEqual(method.failure_reason, "Your card has insufficient funds.")
		self.assertEqual(method.failed_attempts, 1)
		self.assertTrue(method.last_failed_at)
		event_reason = frappe.db.get_value(
			"Billing Event", {"subject": method.name, "to_state": "Failed"}, "reason"
		)
		self.assertEqual(event_reason, "card_declined")

	def test_a_failed_method_is_not_charged_again(self):
		with stub_adapter(validate=False) as adapter:
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			payments.confirm_payment_method(setup["payment_method"])
			adapter.validate_payment_method.reset_mock()

			method = payments.confirm_payment_method(setup["payment_method"])

		adapter.validate_payment_method.assert_not_called()
		self.assertEqual(method.status, "Failed")

	def test_a_card_not_saved_yet_is_not_confirmed(self):
		with stub_adapter() as adapter:
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			adapter.read_saved_card.return_value = {}
			with self.assertRaises(payments.CardNotSaved):
				payments.confirm_payment_method(setup["payment_method"])
		self.assertEqual(
			frappe.db.get_value("Payment Method", setup["payment_method"], "status"), "Pending Validation"
		)

	def test_a_card_saved_to_another_customer_fails(self):
		with stub_adapter(card=saved_card(customer="cus_someone_else")) as adapter:
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"])
		adapter.validate_payment_method.assert_not_called()
		self.assertEqual(method.status, "Failed")


class TestDefaultAndDelete(CardTestBase):
	def test_exactly_one_default_per_team(self):
		first = self.add_active_card()
		second = self.add_active_card(last4="5555")

		# First card is default; second is not, until promoted.
		self.assertTrue(frappe.db.get_value("Payment Method", first, "is_default"))
		self.assertFalse(frappe.db.get_value("Payment Method", second, "is_default"))

		payments.set_default_payment_method(second)
		self.assertFalse(frappe.db.get_value("Payment Method", first, "is_default"))
		self.assertTrue(frappe.db.get_value("Payment Method", second, "is_default"))
		defaults = frappe.get_all("Payment Method", filters={"team": TEAM, "is_default": 1}, pluck="name")
		self.assertEqual(len(defaults), 1)

	def test_non_active_method_cannot_be_default(self):
		with stub_adapter(validate=False):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			payments.confirm_payment_method(setup["payment_method"])
		with self.assertRaises(frappe.ValidationError):
			payments.set_default_payment_method(setup["payment_method"])

	def test_deleting_default_promotes_another(self):
		first = self.add_active_card()
		second = self.add_active_card(last4="5555")

		result = payments.delete_payment_method(first)  # the default
		self.assertEqual(result["new_default"], second)
		self.assertTrue(frappe.db.get_value("Payment Method", second, "is_default"))

	def test_deleting_last_card_leaves_no_default(self):
		only = self.add_active_card()
		result = payments.delete_payment_method(only)
		self.assertIsNone(result["new_default"])
		self.assertFalse(frappe.db.exists("Payment Method", only))


class TestExpiry(CardTestBase):
	def test_past_expiry_card_is_expired_future_one_survives(self):
		stale = self.add_active_card(expiry_month=1, expiry_year=2020)
		fresh = self.add_active_card(expiry_month=12, expiry_year=2099)

		payments.expire_payment_methods(now="2026-06-03")

		self.assertEqual(frappe.db.get_value("Payment Method", stale, "status"), "Expired")
		self.assertEqual(frappe.db.get_value("Payment Method", fresh, "status"), "Active")

	def test_card_valid_through_end_of_expiry_month(self):
		# Expires 06/2026 — still valid on a day within June 2026.
		card = self.add_active_card(expiry_month=6, expiry_year=2026)
		payments.expire_payment_methods(now="2026-06-30")
		self.assertEqual(frappe.db.get_value("Payment Method", card, "status"), "Active")
		payments.expire_payment_methods(now="2026-07-01")
		self.assertEqual(frappe.db.get_value("Payment Method", card, "status"), "Expired")


class TestStripeTestModeIntegration(CardTestBase):
	"""End-to-end add -> validate -> active through the REAL StripeAdapter, with
	only the stripe SDK calls stubbed (test-mode shape)."""

	def test_add_validate_active_via_stripe_adapter(self):
		import stripe

		with (
			patch.object(stripe.SetupIntent, "create") as setup_create,
			patch.object(stripe.Customer, "create") as customer_create,
		):
			setup_create.return_value = {"client_secret": "seti_secret", "id": "seti_1"}
			customer_create.return_value = {"id": "cus_1"}  # off-session SetupIntent needs a customer
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)

		self.assertEqual(setup["client_secret"], "seti_secret")
		self.assertEqual(
			frappe.db.get_value("Payment Method", setup["payment_method"], "status"),
			"Pending Validation",
		)

		# Confirm: the card is read from our SetupIntent, then the micro-charge succeeds
		# and is auto-refunded -> active.
		with (
			patch.object(stripe.SetupIntent, "retrieve") as setup_retrieve,
			patch.object(stripe.PaymentMethod, "retrieve") as method_retrieve,
			patch.object(stripe.PaymentIntent, "create") as pi_create,
			patch.object(stripe.Refund, "create") as refund_create,
		):
			setup_retrieve.return_value = {
				"status": "succeeded",
				"payment_method": "pm_card",
				"customer": "cus_1",
			}
			method_retrieve.return_value = {
				"card": {"brand": "visa", "last4": "4242", "exp_month": 1, "exp_year": 2031}
			}
			pi_create.return_value = {"id": "pi_micro", "status": "succeeded"}
			method = payments.confirm_payment_method(setup["payment_method"])

		setup_retrieve.assert_called_once_with("seti_1")
		self.assertEqual(method.gateway_method_id, "pm_card")

		refund_create.assert_called_once()  # micro-charge refunded
		self.assertEqual(method.status, "Active")
		self.assertTrue(method.is_default)


class TestCardWithoutMandate(CardTestBase):
	"""A card in a currency with no recurring-debit rule is saved without a mandate."""

	def setUp(self):
		from central.billing.platform import readiness
		from central.billing.tests.utils import complete_billing_profile

		super().setUp()
		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		complete_billing_profile(TEAM, currency="USD")
		self.readiness = readiness

	def test_a_usd_card_has_no_mandate_currency(self):
		method = frappe.get_doc("Payment Method", self.add_active_card())
		self.assertFalse(method.mandate_currency)
		self.assertFalse([v for v in self.readiness.check_mandates_in_billing_currency() if v.team == TEAM])


class TestIndianCardMandateSetup(CardTestBase):
	"""An INR card is saved as a mandate, and the mandate the bank issues is stored
	so later debits can quote it (ADR 0022)."""

	def setUp(self):
		from central.billing.tests.utils import complete_billing_profile, set_team_tier

		super().setUp()
		make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		complete_billing_profile(TEAM, currency="INR")
		set_team_tier(TEAM, level="t1", max_spend=50000)

	def test_setup_asks_for_a_mandate_up_to_the_rbi_ceiling(self):
		with stub_adapter() as adapter:
			payments.initiate_payment_method_setup(TEAM, GATEWAY)
		setup_data = adapter.setup_payment_method.call_args.args[1]
		self.assertEqual(setup_data["currency"], "INR")
		self.assertEqual(setup_data["max_amount"], 15000.0)

	def test_a_lower_tier_cap_lowers_what_the_customer_consents_to(self):
		from central.billing.tests.utils import set_team_tier

		set_team_tier(TEAM, level="t0", max_spend=6000)
		with stub_adapter() as adapter:
			payments.initiate_payment_method_setup(TEAM, GATEWAY)
		self.assertEqual(adapter.setup_payment_method.call_args.args[1]["max_amount"], 6000.0)

	def test_the_mandate_reference_is_stored_on_confirm(self):
		with stub_adapter(validate=True, card=saved_card(payment_method="pm_india", mandate="mandate_india")):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"])
		self.assertEqual(method.gateway_mandate_id, "mandate_india")
		self.assertEqual(method.mandate_max_amount, 15000.0)
		self.assertEqual(method.mandate_currency, "INR")
