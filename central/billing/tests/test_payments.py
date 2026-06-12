# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Card Payment Method lifecycle (issue #05)."""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from central.billing.tests.utils import ensure_team

from central.billing.payments import payments
from central.billing.tests.test_stripe_adapter import make_stripe_gateway

TEAM = "team-cards"
GATEWAY = "GW-Test-Stripe"


@contextmanager
def stub_adapter(validate=True):
	"""Resolve a mock GatewayAdapter (no SDK touched)."""
	adapter = MagicMock()
	adapter.setup_payment_method.return_value = {
		"client_secret": "seti_secret_123",
		"setup_intent_id": "seti_123",
	}
	adapter.validate_payment_method.return_value = validate
	adapter.create_customer.return_value = "cus_created"
	with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
		yield adapter


class CardTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		make_stripe_gateway(GATEWAY)
		for name in frappe.get_all("Payment Method", filters={"team": TEAM}, pluck="name"):
			frappe.delete_doc("Payment Method", name, force=True)

	def add_active_card(self, label="Visa ····4242", expiry_month=12, expiry_year=2030):
		with stub_adapter(validate=True):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			payments.confirm_payment_method(
				setup["payment_method"],
				gateway_method_id=f"pm_{frappe.generate_hash(6)}",
				display_label=label,
				expiry_month=expiry_month,
				expiry_year=expiry_year,
			)
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
		with stub_adapter(validate=True) as adapter:
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(
				setup["payment_method"], gateway_method_id="pm_live", display_label="Visa ····4242"
			)
		adapter.validate_payment_method.assert_called_once()  # micro-charge ran
		self.assertEqual(method.status, "Active")
		self.assertEqual(method.gateway_method_id, "pm_live")
		self.assertTrue(method.validated_at)
		self.assertTrue(method.is_default)  # first active method becomes default

	def test_failed_microcharge_leaves_method_failed(self):
		with stub_adapter(validate=False):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			method = payments.confirm_payment_method(setup["payment_method"], gateway_method_id="pm_bad")
		self.assertEqual(method.status, "Failed")
		self.assertFalse(method.is_default)


class TestDefaultAndDelete(CardTestBase):
	def test_exactly_one_default_per_team(self):
		first = self.add_active_card()
		second = self.add_active_card(label="MC ····5555")

		# First card is default; second is not, until promoted.
		self.assertTrue(frappe.db.get_value("Payment Method", first, "is_default"))
		self.assertFalse(frappe.db.get_value("Payment Method", second, "is_default"))

		payments.set_default_payment_method(second)
		self.assertFalse(frappe.db.get_value("Payment Method", first, "is_default"))
		self.assertTrue(frappe.db.get_value("Payment Method", second, "is_default"))
		defaults = frappe.get_all(
			"Payment Method", filters={"team": TEAM, "is_default": 1}, pluck="name"
		)
		self.assertEqual(len(defaults), 1)

	def test_non_active_method_cannot_be_default(self):
		with stub_adapter(validate=False):
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)
			payments.confirm_payment_method(setup["payment_method"], gateway_method_id="pm_bad")
		with self.assertRaises(frappe.ValidationError):
			payments.set_default_payment_method(setup["payment_method"])

	def test_deleting_default_promotes_another(self):
		first = self.add_active_card()
		second = self.add_active_card(label="MC ····5555")

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

		with patch.object(stripe.SetupIntent, "create") as setup_create, patch.object(
			stripe.Customer, "create"
		) as customer_create:
			setup_create.return_value = {"client_secret": "seti_secret", "id": "seti_1"}
			customer_create.return_value = {"id": "cus_1"}  # off-session SetupIntent needs a customer
			setup = payments.initiate_payment_method_setup(TEAM, GATEWAY)

		self.assertEqual(setup["client_secret"], "seti_secret")
		self.assertEqual(
			frappe.db.get_value("Payment Method", setup["payment_method"], "status"),
			"Pending Validation",
		)

		# Confirm: the micro-charge succeeds and is auto-refunded -> active.
		with patch.object(stripe.PaymentIntent, "create") as pi_create, patch.object(
			stripe.Refund, "create"
		) as refund_create:
			pi_create.return_value = {"id": "pi_micro", "status": "succeeded"}
			method = payments.confirm_payment_method(
				setup["payment_method"],
				gateway_method_id="pm_card",
				gateway_customer_id="cus_1",
				display_label="Visa ····4242",
			)

		refund_create.assert_called_once()  # micro-charge refunded
		self.assertEqual(method.status, "Active")
		self.assertTrue(method.is_default)
