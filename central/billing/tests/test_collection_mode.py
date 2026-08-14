# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the ₹15,000 Action Required threshold (ADR 0005, ADR 0022)."""

import frappe

from central.billing.payments import collection_mode
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import clear_team_tier, complete_billing_profile, ensure_team, set_team_tier

TEAM = "team-collection"


def _set_mode(team, mode, reason=None):
	doc = frappe.get_doc("Billing Profile", team)
	doc.collection_mode = mode
	doc.collection_action_reason = reason
	doc.save(ignore_permissions=True)


class TestCollectionMode(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		clear_team_tier(TEAM)  # no tier → flat ₹15k threshold
		frappe.db.delete("Billing Notification Log", {"team": TEAM})

	def test_threshold_is_15k_without_a_tier(self):
		self.assertEqual(collection_mode.silent_threshold(TEAM), 15000.0)

	def test_threshold_is_capped_by_a_lower_tier(self):
		set_team_tier(TEAM, level="t0", max_spend=8000)
		self.assertEqual(collection_mode.silent_threshold(TEAM), 8000.0)

	def test_auto_charge_under_threshold_stays_silent(self):
		_set_mode(TEAM, "Auto Charge")
		st = collection_mode.evaluate(TEAM, projected_amount=9000)
		self.assertEqual(st["collection_mode"], "Auto Charge")
		self.assertFalse(st["action_required"])

	def test_auto_charge_over_threshold_trips_action_required(self):
		_set_mode(TEAM, "Auto Charge")
		st = collection_mode.evaluate(TEAM, projected_amount=18400)
		self.assertEqual(st["collection_mode"], "Action Required")
		self.assertTrue(st["action_required"])
		self.assertEqual(st["reason"], "forecast_over_threshold")
		# A notification was raised for the customer to act on.
		self.assertTrue(
			frappe.db.exists("Billing Notification Log", {"team": TEAM, "event_type": "Action Required"})
		)

	def test_trip_is_idempotent_one_notification(self):
		_set_mode(TEAM, "Auto Charge")
		collection_mode.evaluate(TEAM, projected_amount=20000)
		collection_mode.evaluate(TEAM, projected_amount=25000)
		self.assertEqual(
			frappe.db.count("Billing Notification Log", {"team": TEAM, "event_type": "Action Required"}), 1
		)

	def test_modes_that_never_charge_silently_are_never_tripped(self):
		# A prepaid team running a huge bill is not "action required" — it just draws
		# the wallet; only the silent off-session rail has the ₹15k ceiling.
		_set_mode(TEAM, "Prepaid")
		st = collection_mode.evaluate(TEAM, projected_amount=99999)
		self.assertEqual(st["collection_mode"], "Prepaid")
		self.assertFalse(st["action_required"])

	def test_customer_chooses_manual_checkout_clears_action(self):
		_set_mode(TEAM, "Action Required", reason="forecast_over_threshold")
		st = collection_mode.choose(TEAM, "Manual Checkout")
		self.assertEqual(st["collection_mode"], "Manual Checkout")
		self.assertFalse(st["action_required"])
		self.assertIsNone(frappe.db.get_value("Billing Profile", TEAM, "collection_action_reason"))

	def test_customer_chooses_prepaid_clears_action(self):
		_set_mode(TEAM, "Action Required", reason="forecast_over_threshold")
		st = collection_mode.choose(TEAM, "Prepaid")
		self.assertEqual(st["collection_mode"], "Prepaid")
		self.assertFalse(st["action_required"])

	def test_returning_to_auto_needs_something_to_charge(self):
		"""Auto Charge means "we debit something". Without a method it is a mode whose
		first invoice would discover the gap for the customer."""
		_set_mode(TEAM, "Prepaid")
		frappe.db.delete("Payment Method", {"team": TEAM})
		with self.assertRaises(frappe.ValidationError):
			collection_mode.choose(TEAM, "Auto Charge")

	def test_a_team_with_a_working_method_can_go_back_to_auto(self):
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway().name
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": gw,
				"method_type": "Card",
				"status": "Active",
				"display_label": "Visa ····4242",
				"gateway_method_id": "pm_back_to_auto",
				"validated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		_set_mode(TEAM, "Prepaid")

		st = collection_mode.choose(TEAM, "Auto Charge")

		self.assertEqual(st["collection_mode"], "Auto Charge")
		frappe.db.delete("Payment Method", {"team": TEAM})

	def test_a_method_awaiting_reauth_does_not_count(self):
		"""It is skipped by the charge loop, so it cannot be what auto-pay rests on."""
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		gw = make_stripe_gateway().name
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": gw,
				"method_type": "UPI Autopay",
				"status": "Active",
				"reauth_required": 1,
				"gateway_method_id": "tok_reauth",
				"validated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		_set_mode(TEAM, "Prepaid")
		with self.assertRaises(frappe.ValidationError):
			collection_mode.choose(TEAM, "Auto Charge")
		frappe.db.delete("Payment Method", {"team": TEAM})

	def test_invalid_mode_choice_is_rejected(self):
		_set_mode(TEAM, "Action Required")
		# A customer cannot silently put themselves (back) on a silent auto rail.
		with self.assertRaises(frappe.ValidationError):
			collection_mode.choose(TEAM, "Nonsense Mode")


class TestInvoiceTimeTrip(IntegrationTestCase):
	"""pay_invoice refuses an INR debit over ₹15k and trips Action Required instead
	of attempting a doomed off-session charge."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		_set_mode(TEAM, "Auto Charge")
		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Invoice", {"team": TEAM})
		self.gw = make_razorpay_gateway().name
		self.pm = (
			frappe.get_doc(
				{
					"doctype": "Payment Method",
					"team": TEAM,
					"gateway": self.gw,
					"method_type": "UPI Autopay",
					"status": "Active",
					"display_label": "UPI",
					"gateway_method_id": "tok_x",
					"gateway_customer_id": "cus_x",
					"mandate_max_amount": 200000,
					"mandate_currency": "INR",
					"is_default": 1,
					"validated_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _invoice(self, amount):
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
					"subtotal": amount,
					"total": amount,
					"expected_collection": amount,
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": amount, "days": 30, "amount": amount}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_charge_over_15k_trips_action_required_and_does_not_attempt(self):
		from central.billing.payments import charges

		inv = self._invoice(20000)  # ₹20,000 — over the silent ceiling
		out = charges.pay_invoice(inv, payment_method=self.pm, gateway=self.gw)
		self.assertFalse(out["charged"])
		self.assertEqual(out["reason"], "action_required")
		# No Payment Attempt was created — we never hit the gateway.
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 0)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "collection_mode"), "Action Required")


class TestManualCheckout(IntegrationTestCase):
	"""On-session pay-an-invoice for Manual Checkout teams: any amount, settled by
	the webhook (never on confirm)."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		_set_mode(TEAM, "Manual Checkout")
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Invoice", {"team": TEAM})
		self.gw = make_razorpay_gateway().name

	def _invoice(self, amount):
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
					"subtotal": amount,
					"total": amount,
					"expected_collection": amount,
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": amount, "days": 30, "amount": amount}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_checkout_settles_only_on_webhook_for_any_amount(self):
		from unittest.mock import MagicMock, patch

		from central.billing.payments import charges

		inv = self._invoice(40000)  # ₹40,000 — far over the off-session ceiling, fine on-session
		adapter = MagicMock()
		adapter.create_order.return_value = {
			"order_id": "order_inv",
			"key_id": "rzp",
			"amount_in_subunits": 4000000,
		}
		adapter.verify_payment_signature.return_value = True
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = charges.create_invoice_payment_order(inv, gateway=self.gw)
			self.assertTrue(order["created"])
			self.assertEqual(order["order_id"], "order_inv")
			attempt = order["attempt"]
			self.assertEqual(frappe.db.get_value("Payment Attempt", attempt, "status"), "Initiated")

			out = charges.confirm_invoice_payment(
				attempt,
				razorpay_order_id="order_inv",
				razorpay_payment_id="pay_inv",
				razorpay_signature="sig",
			)
			self.assertTrue(out["confirmed"])
			# Attempt captured + stamped, but the invoice is NOT Paid yet (webhook-truth).
			self.assertEqual(
				frappe.db.get_value("Payment Attempt", attempt, "gateway_transaction_id"), "pay_inv"
			)
			self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Open")

	def test_bad_signature_is_rejected(self):
		from unittest.mock import MagicMock, patch

		from central.billing.payments import charges

		inv = self._invoice(5000)
		adapter = MagicMock()
		adapter.create_order.return_value = {"order_id": "o", "key_id": "rzp"}
		adapter.verify_payment_signature.return_value = False
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			order = charges.create_invoice_payment_order(inv, gateway=self.gw)
			with self.assertRaises(frappe.ValidationError):
				charges.confirm_invoice_payment(
					order["attempt"], razorpay_payment_id="p", razorpay_signature="bad"
				)


class TestModeAwareDunning(IntegrationTestCase):
	"""Dunning never silently retries a manual_checkout / action_required team, and
	its overdue copy names the mode-appropriate action (#50 item 2)."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		ensure_team(TEAM)
		complete_billing_profile(TEAM)
		frappe.db.delete("Payment Attempt", {"team": TEAM})
		frappe.db.delete("Invoice", {"team": TEAM})
		frappe.db.delete("Payment Method", {"team": TEAM})
		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		self.gw = make_razorpay_gateway().name
		# An active method exists — so a retry WOULD happen if the mode allowed it.
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": TEAM,
				"gateway": self.gw,
				"method_type": "UPI Autopay",
				"status": "Active",
				"gateway_method_id": "tok",
				"gateway_customer_id": "cus",
				"mandate_max_amount": 200000,
				"mandate_currency": "INR",
				"is_default": 1,
				"validated_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)

	def _overdue_invoice(self, amount=5000):
		return (
			frappe.get_doc(
				{
					"doctype": "Invoice",
					"team": TEAM,
					"invoice_type": "Billable",
					"status": "Open",
					"period_start": "2026-05-01",
					"period_end": "2026-05-31",
					"currency": "INR",
					"subtotal": amount,
					"total": amount,
					"expected_collection": amount,
					"due_date": "2026-06-01",
					"items": [
						{"resource_type": "bundle", "plan": "p", "rate": amount, "days": 30, "amount": amount}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_manual_checkout_is_not_retried_and_copy_says_pay(self):
		from central.billing.revenue import dunning

		_set_mode(TEAM, "Manual Checkout")
		inv = self._overdue_invoice()
		dunning.process_invoice_dunning(inv, now="2026-06-10")  # 9 days overdue
		self.assertEqual(frappe.db.count("Payment Attempt", {"invoice": inv}), 0)  # no silent retry
		self.assertEqual(frappe.db.get_value("Invoice", inv, "status"), "Overdue")
		msg = frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Invoice Overdue"}, "message"
		)
		self.assertIn("pay it now", msg)

	def test_prepaid_copy_says_top_up(self):
		from central.billing.revenue import dunning

		_set_mode(TEAM, "Prepaid")
		inv = self._overdue_invoice()
		dunning.process_invoice_dunning(inv, now="2026-06-10")
		msg = frappe.db.get_value(
			"Billing Notification Log", {"team": TEAM, "event_type": "Invoice Overdue"}, "message"
		)
		self.assertIn("top up", msg.lower())


class TestSilentChargeCapability(IntegrationTestCase):
	"""Which rail may auto-charge how much, per currency (ADR 0022)."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
		from central.billing.tests.test_stripe_adapter import make_stripe_gateway

		self.stripe = make_stripe_gateway(currencies=(("USD", 1), ("INR", 0)))
		self.razorpay = make_razorpay_gateway()

	def _adapter(self, gateway):
		from central.billing.gateways.registry import get_adapter

		return get_adapter(gateway)

	def test_stripe_usd_has_no_ceiling(self):
		a = self._adapter(self.stripe)
		self.assertTrue(a.supports_off_session_charge)
		self.assertTrue(a.can_charge_silently(10_00_000, "USD"))

	def test_stripe_inr_is_capped_like_everyone_else(self):
		"""The ₹15,000 rule is the RBI's, so moving the rail to Stripe does not move it."""
		a = self._adapter(self.stripe)
		self.assertTrue(a.can_charge_silently(15000, "INR"))
		self.assertFalse(a.can_charge_silently(15000.01, "INR"))

	def test_razorpay_inr_is_capped_and_notifies(self):
		from central.billing.gateways import capabilities

		a = self._adapter(self.razorpay)
		self.assertTrue(a.can_charge_silently(15000, "INR"))
		self.assertFalse(a.can_charge_silently(15001, "INR"))
		self.assertTrue(capabilities.requires_predebit_notice(self.razorpay.name, "INR"))

	def test_inr_is_capped_even_where_the_row_says_nothing(self):
		"""An unfilled ceiling must not read as "no ceiling" for a regulated currency."""
		from central.billing.tests.utils import configure_gateway

		gw = configure_gateway("Stripe", (("USD", 1),), is_enabled=1)
		self.assertFalse(self._adapter(gw).can_charge_silently(20000, "INR"))

	def test_inr_ceiling_cannot_be_configured_above_the_rbi_limit(self):
		from central.billing.tests.utils import configure_gateway

		gw = configure_gateway("Razorpay", (("INR", 1),), is_enabled=1)
		gw.currencies[0].max_silent_charge = 50000
		gw.save(ignore_permissions=True)
		self.assertEqual(gw.currencies[0].max_silent_charge, 15000)

	def test_a_stricter_inr_ceiling_is_left_alone(self):
		from central.billing.tests.utils import configure_gateway

		gw = configure_gateway("Razorpay", (("INR", 1),), is_enabled=1)
		gw.currencies[0].max_silent_charge = 5000
		gw.save(ignore_permissions=True)
		self.assertEqual(gw.currencies[0].max_silent_charge, 5000)
