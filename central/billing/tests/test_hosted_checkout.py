# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Pilot hosted checkout: create stores what Central asked for, and the poll settles
only that record, for the credential's own team."""

import inspect
import json
from unittest.mock import MagicMock, patch

import frappe

from central.billing.api import billing_api
from central.billing.gateways.base import VerifiedPayment
from central.billing.payments import webhooks
from central.billing.revenue import credits
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, complete_billing_profile, ensure_team

TEAM = "team-hosted"
OTHER = "team-hosted-other"


class TestHostedCheckout(BillingTestCase):
	def setUp(self):
		make_stripe_gateway(currencies=(("INR", 1),))
		for team in (TEAM, OTHER):
			ensure_team(team)
			complete_billing_profile(team)
			for doctype in (
				"Top-up Order",
				"Credit Ledger Entry",
				"Credit Wallet",
				"Invoice",
				"Payment Attempt",
			):
				frappe.db.delete(doctype, {"team": team})
		self.create_topup = inspect.unwrap(billing_api.create_topup_checkout)
		self.create_invoice = inspect.unwrap(billing_api.create_invoice_checkout)
		self.status = inspect.unwrap(billing_api.get_checkout_status)
		self.adapter = MagicMock()
		self.adapter.create_customer.return_value = "cus_hosted"
		self.enterContext(patch("central.billing.gateways.registry.get_adapter", return_value=self.adapter))
		self._act_as(TEAM)

	def _act_as(self, team):
		frappe.local.pilot_credential = frappe._dict(team=team)

	def _session(self, session_id):
		self.adapter.create_checkout_session.return_value = {
			"checkout_url": "https://pay",
			"session_id": session_id,
		}

	def _paid(self, session_id, amount):
		self.adapter.checkout_payment.return_value = VerifiedPayment(
			f"pi_{session_id}", True, amount, "INR", order_id=session_id
		)

	def test_a_paid_top_up_credits_the_teams_own_wallet(self):
		self._session("cs_top")
		reference = self.create_topup(amount=500, redirect_url="https://site")["reference"]
		self.assertEqual(
			self.adapter.create_checkout_session.call_args.args[2],
			frappe.db.get_value("Top-up Order", {"gateway_order_id": "cs_top"}, "name"),
		)  # our stored order is the receipt
		self._paid("cs_top", 500)

		out = self.status(reference=reference)

		self.assertEqual(out["status"], "paid")
		self.assertEqual(credits.get_balance(TEAM)["balance"], 500)

	def test_an_unpaid_checkout_is_pending(self):
		self._session("cs_wait")
		reference = self.create_topup(amount=500, redirect_url="https://site")["reference"]
		self.adapter.checkout_payment.return_value = None

		self.assertEqual(self.status(reference=reference)["status"], "pending")

	def test_another_teams_session_is_refused(self):
		self._session("cs_theirs")
		reference = self.create_topup(amount=500, redirect_url="https://site")["reference"]
		self._paid("cs_theirs", 500)

		self._act_as(OTHER)
		# A reference rewritten to name the other team still resolves to the stored owner.
		with self.assertRaises(frappe.PermissionError):
			self.status(reference=reference.replace(f"|{TEAM}", f"|{OTHER}"))
		self.assertEqual(credits.get_balance(OTHER)["balance"], 0)

	def test_a_session_central_never_created_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			self.status(reference=f"Stripe|cs_forged|topup|{TEAM}")

	def test_a_reference_with_no_session_id_is_refused(self):
		from central.billing.doctype.top_up_order.top_up_order import TopupOrder

		# An order whose gateway call never returned has no session id yet.
		TopupOrder.start(TEAM, "Stripe", "INR", 500)

		for reference in ("", "Stripe||topup|" + TEAM, "  "):
			with self.assertRaises(frappe.DoesNotExistError):
				self.status(reference=reference)
		self.adapter.checkout_payment.assert_not_called()

	def test_a_checkout_the_gateway_refuses_frees_the_invoice(self):
		invoice = self._open_invoice()
		self.adapter.create_checkout_session.side_effect = RuntimeError("gateway down")

		with self.assertRaises(RuntimeError):
			self.create_invoice(invoice=invoice.name, redirect_url="https://site")

		self.assertEqual(
			frappe.db.get_value("Payment Attempt", {"invoice": invoice.name}, "status"), "Failed"
		)
		self.adapter.create_checkout_session.side_effect = None
		self._session("cs_again")
		self.assertTrue(self.create_invoice(invoice=invoice.name, redirect_url="https://site")["reference"])

	def _open_invoice(self):
		return frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": "2026-09-01",
				"period_end": "2026-09-30",
				"currency": "INR",
				"subtotal": 800,
				"total": 800,
				"expected_collection": 800,
			}
		).insert(ignore_permissions=True)

	def test_a_paid_invoice_checkout_settles_the_invoice(self):
		invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": "2026-09-01",
				"period_end": "2026-09-30",
				"currency": "INR",
				"subtotal": 800,
				"total": 800,
				"expected_collection": 800,
			}
		).insert(ignore_permissions=True)
		self._session("cs_inv")
		reference = self.create_invoice(invoice=invoice.name, redirect_url="https://site")["reference"]
		self._paid("cs_inv", 800)

		out = self.status(reference=reference)

		self.assertEqual(out["invoice_status"], "Paid")
		attempt = frappe.db.get_value(
			"Payment Attempt", {"gateway_order_id": "cs_inv"}, "gateway_transaction_id"
		)
		self.assertEqual(attempt, "pi_cs_inv")  # recorded, so a refund can find the charge


class TestHostedCardSetupInRegulatedCurrency(BillingTestCase):
	"""Hosted Stripe card setup registers no India mandate, so INR teams add cards on Razorpay."""

	def setUp(self):
		from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway

		validated = {"credentials_validated_at": frappe.utils.now_datetime()}
		make_stripe_gateway(currencies=(("INR", 1), ("USD", 1)))
		frappe.db.set_value("Payment Gateway", "Stripe", validated)
		make_razorpay_gateway(currencies=(("INR", 0),))
		frappe.db.set_value("Payment Gateway", "Razorpay", validated)

		self.gateways = inspect.unwrap(billing_api.get_payment_gateways)
		self.create_card_checkout = inspect.unwrap(billing_api.create_payment_method_checkout)
		self.adapter = MagicMock()
		self.enterContext(patch("central.billing.gateways.registry.get_adapter", return_value=self.adapter))

	def _act_as(self, currency):
		team = f"team-hosted-card-{currency.lower()}"
		ensure_team(team)
		complete_billing_profile(team, currency=currency)
		frappe.local.pilot_credential = frappe._dict(team=team)

	def test_an_inr_team_is_offered_razorpay_only(self):
		self._act_as("INR")

		self.assertEqual([gateway["adapter_key"] for gateway in self.gateways()], ["Razorpay"])

	def test_an_inr_team_cannot_open_a_hosted_stripe_card_setup(self):
		self._act_as("INR")

		with self.assertRaises(frappe.ValidationError):
			self.create_card_checkout(redirect_url="https://site", gateway="Stripe")
		self.adapter.create_setup_checkout_session.assert_not_called()

	def _open_usd_card_setup(self) -> dict:
		self._act_as("USD")
		self.adapter.create_customer.return_value = "cus_usd"
		self.adapter.create_setup_checkout_session.return_value = {
			"checkout_url": "https://setup",
			"session_id": "cs_usd",
			"setup_intent_id": "seti_usd",
		}
		return self.create_card_checkout(redirect_url="https://site", gateway="Stripe")

	def test_a_usd_team_still_gets_hosted_stripe_card_setup(self):
		checkout = self._open_usd_card_setup()

		self.assertEqual([gateway["adapter_key"] for gateway in self.gateways()], ["Stripe"])
		self.assertEqual(checkout["checkout_url"], "https://setup")

	def test_a_card_that_fails_verification_says_so(self):
		from central.billing.tests.test_payments import card_check, saved_card

		reference = self._open_usd_card_setup()["reference"]
		self.adapter.read_saved_card.return_value = saved_card(customer="cus_usd")
		self.adapter.validate_payment_method.return_value = card_check(False)

		result = inspect.unwrap(billing_api.confirm_payment_method_checkout)(reference=reference)

		self.assertEqual(result["status"], "Failed")
		self.assertEqual(
			result["message"],
			"There wasn't enough balance. Try another card, or add credit to your account instead.",
		)

	def _receive_setup_event(self, event_type: str, setup_intent: dict) -> str:
		payload = {"id": f"evt_{event_type}", "type": event_type, "data": {"object": setup_intent}}
		event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": "Stripe",
				"gateway_event_id": payload["id"],
				"event_type": event_type,
				"raw_payload": json.dumps(payload),
				"status": "Received",
			}
		).insert(ignore_permissions=True)
		webhooks.handle_webhook_event(event.name)
		return event.name

	def test_a_declined_hosted_card_setup_is_kept_on_its_card(self):
		method = self._open_usd_card_setup()["reference"].split("|")[-1]
		failure = {"code": "card_declined", "message": "Your card was declined."}

		self._receive_setup_event(
			"setup_intent.setup_failed", {"id": "seti_usd", "last_setup_error": failure}
		)

		failed = frappe.db.get_value(
			"Payment Method", method, ["status", "failure_code", "failed_attempts"], as_dict=True
		)
		self.assertEqual(
			(failed.status, failed.failure_code, failed.failed_attempts),
			("Pending Validation", "card_declined", 1),
		)
		self.assertTrue(
			frappe.db.exists(
				"Billing Event",
				{"subject": method, "event_type": "Payment Method Setup Failed", "reason": "card_declined"},
			)
		)

	def test_a_setup_event_that_is_not_a_failure_leaves_the_card_alone(self):
		method = self._open_usd_card_setup()["reference"].split("|")[-1]

		events = [
			self._receive_setup_event(event_type, {"id": "seti_usd"})
			for event_type in (
				"setup_intent.created",
				"setup_intent.requires_action",
				"setup_intent.succeeded",
			)
		]

		card = frappe.db.get_value("Payment Method", method, ["status", "failed_attempts"], as_dict=True)
		self.assertEqual((card.status, card.failed_attempts), ("Pending Validation", 0))
		self.assertFalse(
			frappe.db.exists(
				"Billing Event", {"subject": method, "event_type": "Payment Method Setup Failed"}
			)
		)
		statuses = {frappe.db.get_value("Webhook Event", name, "status") for name in events}
		self.assertEqual(statuses, {"Ignored"})


class TestInAppBillingProfile(BillingTestCase):
	"""The in-app address form picks country and Indian state from lists Central owns."""

	def test_the_profile_carries_the_country_and_india_state_lists(self):
		from central.billing.india_gst import india_state_options

		team = "team-hosted-profile"
		ensure_team(team)
		complete_billing_profile(team, currency="INR")
		frappe.local.pilot_credential = frappe._dict(team=team)

		profile = inspect.unwrap(billing_api.get_billing_profile)()

		self.assertEqual(profile["legal_name"], f"{team} Ltd")
		self.assertIn("India", profile["countries"])
		self.assertEqual(profile["india_states"], india_state_options())
