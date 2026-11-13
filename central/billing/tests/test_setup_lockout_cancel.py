# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import json
from unittest.mock import MagicMock, patch

import frappe
import stripe

from central.billing.gateways.base import GatewayUnsupported
from central.billing.gateways.stripe_adapter import StripeAdapter
from central.billing.payments import payments, setup_lockout_cancel, webhooks
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import (
	BillingTestCase,
	complete_billing_profile,
	configure_gateway,
	ensure_team,
	make_user,
	run_enqueued_inline,
)

TEAM = "team-lock-cancel"
OTHER_TEAM = "team-lock-cancel-other"
THIRD_TEAM = "team-lock-cancel-third"
DECLINED = {"failure_code": "card_declined", "decline_code": "do_not_honor"}


class TestSetupLockoutCancel(BillingTestCase):
	def setUp(self):
		for team in (TEAM, OTHER_TEAM, THIRD_TEAM):
			ensure_team(team)
		complete_billing_profile(TEAM)
		make_stripe_gateway()
		self.user = make_user("lock-cancel-user@example.com")
		for target, kwargs in (
			("frappe.enqueue", {"side_effect": run_enqueued_inline}),
			("central.billing.platform.alerts.notify_operators", {"return_value": ["Email"]}),
		):
			patcher = patch(target, **kwargs)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.adapter = MagicMock()
		self.adapter.cancel_setup.return_value = "canceled"
		self.adapter.cancel_order.return_value = "canceled"
		patcher = patch("central.billing.gateways.registry.get_adapter", return_value=self.adapter)
		patcher.start()
		self.addCleanup(patcher.stop)

	def fail(self, times=1, team=TEAM, user=None):
		"""Bank refusals on a setup that holds no gateway object of its own."""
		method = self.make_method(team, user, setup_reference=None)
		for _ in range(times):
			payments._record_setup_failure(method, DECLINED)

	def make_method(self, team=TEAM, user=None, setup_reference="seti_open", gateway="Stripe") -> str:
		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": team,
				"gateway": gateway,
				"method_type": "Card",
				"status": "Pending Validation",
				"setup_reference": setup_reference,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Payment Method", method.name, "owner", user or "Administrator")
		return method.name

	def make_top_up(self, team=TEAM, user=None, order_id="pi_open") -> str:
		order = frappe.get_doc(
			{
				"doctype": "Top-up Order",
				"team": team,
				"gateway": "Stripe",
				"currency": "INR",
				"total": 500,
				"gateway_order_id": order_id,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Top-up Order", order.name, "owner", user or "Administrator")
		return order.name

	def status(self, doctype, name):
		return frappe.db.get_value(doctype, name, "status")

	def receive(self, event_type: str, gateway_object: dict) -> str:
		payload = {
			"id": f"evt_{frappe.generate_hash(8)}",
			"type": event_type,
			"data": {"object": gateway_object},
		}
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
		return self.status("Webhook Event", event.name)

	def test_the_fifth_failure_cancels_the_open_setup_and_top_up_once(self):
		method, order = self.make_method(), self.make_top_up()
		self.fail(times=4)
		self.adapter.cancel_setup.assert_not_called()
		self.adapter.cancel_order.assert_not_called()

		self.fail(times=2)
		self.adapter.cancel_setup.assert_called_once_with("seti_open")
		self.adapter.cancel_order.assert_called_once_with("pi_open")
		self.assertEqual(self.status("Payment Method", method), "Cancelled")
		self.assertEqual(self.status("Top-up Order", order), "Expired")
		self.assertTrue(
			frappe.db.exists(
				"Billing Event",
				{"subject": method, "to_state": "Cancelled", "reason": setup_lockout_cancel.REASON},
			)
		)

	def test_the_cancel_runs_in_a_job_after_the_failure_commits(self):
		with patch("frappe.enqueue") as enqueue:
			self.fail(times=5)
		closes = [c for c in enqueue.call_args_list if c.args[0].endswith("setup_lockout_cancel.close_open")]
		self.assertEqual(len(closes), 1)
		self.assertTrue(closes[0].kwargs["enqueue_after_commit"])

	def test_an_intent_stripe_cannot_cancel_is_left_open(self):
		self.adapter.cancel_setup.return_value = "succeeded"
		self.adapter.cancel_order.return_value = "processing"
		method, order = self.make_method(), self.make_top_up()
		self.fail(times=5)
		self.assertEqual(self.status("Payment Method", method), "Pending Validation")
		self.assertEqual(self.status("Top-up Order", order), "Created")

	def test_a_gateway_that_cannot_cancel_leaves_the_setup(self):
		configure_gateway("Razorpay", (("INR", 1),))
		self.adapter.cancel_setup.side_effect = GatewayUnsupported("no cancel")
		method = self.make_method(setup_reference="order_open", gateway="Razorpay")
		errors = frappe.db.count("Error Log")
		self.fail(times=5)
		self.assertEqual(self.status("Payment Method", method), "Pending Validation")
		self.assertEqual(frappe.db.count("Error Log"), errors)

	def test_a_saved_card_awaiting_its_check_is_not_cancelled(self):
		method = self.make_method()
		frappe.db.set_value("Payment Method", method, "gateway_method_id", "pm_saved")
		self.fail(times=5)
		self.adapter.cancel_setup.assert_not_called()

	def test_a_locked_user_loses_their_open_setups_in_other_teams(self):
		theirs = self.make_method(OTHER_TEAM, self.user, "seti_theirs")
		someone_elses = self.make_method(OTHER_TEAM, make_user(), "seti_someone_else")
		same_team_other_member = self.make_method(TEAM, make_user(), "seti_same_team")
		self.fail(times=3, team=TEAM, user=self.user)
		self.fail(times=2, team=THIRD_TEAM, user=self.user)

		self.assertEqual(self.status("Payment Method", theirs), "Cancelled")
		self.assertEqual(self.status("Payment Method", someone_elses), "Pending Validation")
		self.assertEqual(self.status("Payment Method", same_team_other_member), "Pending Validation")

	def test_a_team_the_operator_cleared_keeps_the_users_setup(self):
		from central.billing.api.admin.teams import clear_setup_lock

		complete_billing_profile(OTHER_TEAM)
		theirs = self.make_method(OTHER_TEAM, self.user, "seti_theirs")
		self.fail(times=4, team=TEAM, user=self.user)
		clear_setup_lock(OTHER_TEAM)
		self.fail(times=1, team=THIRD_TEAM, user=self.user)
		self.assertEqual(self.status("Payment Method", theirs), "Pending Validation")

	def test_a_later_setup_intent_canceled_webhook_is_a_no_op(self):
		method = self.make_method()
		self.fail(times=5)
		self.assertEqual(self.receive("setup_intent.canceled", {"id": "seti_open"}), "Ignored")
		self.assertEqual(self.status("Payment Method", method), "Cancelled")

	def test_a_cancelled_top_up_intent_is_not_counted_again(self):
		order = self.make_top_up()
		self.fail(times=5)
		declines = frappe.db.count("Billing Event", {"subject": order})
		intent = {
			"object": "payment_intent",
			"id": "pi_open",
			"status": "canceled",
			"amount": 50000,
			"currency": "inr",
			"metadata": {"receipt": order},
			"cancellation_reason": "abandoned",
			"last_payment_error": {"code": "card_declined", "decline_code": "do_not_honor"},
		}
		self.assertEqual(self.receive("payment_intent.canceled", intent), "Ignored")
		self.assertEqual(frappe.db.count("Billing Event", {"subject": order}), declines)

	def test_a_payment_that_lands_after_the_cancel_still_credits(self):
		order = self.make_top_up(order_id="pi_late")
		self.assertEqual(setup_lockout_cancel.close_top_up(order), "Expired")
		intent = {
			"object": "payment_intent",
			"id": "pi_late",
			"status": "succeeded",
			"amount_received": 50000,
			"currency": "inr",
			"metadata": {"receipt": order},
		}
		self.assertEqual(self.receive("payment_intent.succeeded", intent), "Processed")
		self.assertEqual(self.status("Top-up Order", order), "Credited")
		self.assertEqual(frappe.db.count("Credit Ledger Entry", {"reference_name": "pi_late"}), 1)


class _FakeStripeHTTP(stripe.HTTPClient):
	"""Answers every Stripe request with one canned response, and keeps the request."""

	name = "fake"

	def __init__(self, status: int, body: dict):
		super().__init__()
		self.status, self.body, self.calls = status, body, []

	def request(self, method, url, headers, post_data=None):
		self.calls.append((method, url, post_data))
		return json.dumps(self.body), self.status, {}


class TestStripeCancelRealClient(BillingTestCase):
	"""The real stripe-python client, with only its HTTP stubbed, so a wrong call signature fails."""

	def setUp(self):
		self.adapter = StripeAdapter(make_stripe_gateway())

	def respond(self, status: int, body: dict) -> _FakeStripeHTTP:
		client = _FakeStripeHTTP(status, body)
		patcher = patch.object(stripe, "default_http_client", client)
		patcher.start()
		self.addCleanup(patcher.stop)
		return client

	def test_a_setup_intent_is_cancelled(self):
		client = self.respond(200, {"id": "seti_1", "object": "setup_intent", "status": "canceled"})
		self.assertEqual(self.adapter.cancel_setup("seti_1"), "canceled")
		method, url, post_data = client.calls[0]
		self.assertEqual((method, url), ("post", "https://api.stripe.com/v1/setup_intents/seti_1/cancel"))
		self.assertIn("cancellation_reason=abandoned", post_data)

	def test_a_payment_intent_is_cancelled(self):
		client = self.respond(200, {"id": "pi_1", "object": "payment_intent", "status": "canceled"})
		self.assertEqual(self.adapter.cancel_order("pi_1"), "canceled")
		self.assertTrue(client.calls[0][1].endswith("/v1/payment_intents/pi_1/cancel"))

	def test_a_checkout_session_is_expired(self):
		client = self.respond(200, {"id": "cs_1", "object": "checkout.session", "status": "expired"})
		self.assertEqual(self.adapter.cancel_setup("cs_1"), "expired")
		self.assertTrue(client.calls[0][1].endswith("/v1/checkout/sessions/cs_1/expire"))

	def test_a_succeeded_intent_is_a_no_op(self):
		self.respond(
			400,
			{
				"error": {
					"type": "invalid_request_error",
					"code": "payment_intent_unexpected_state",
					"message": "You cannot cancel this PaymentIntent because it has a status of succeeded.",
					"payment_intent": {"id": "pi_1", "status": "succeeded"},
				}
			},
		)
		self.assertEqual(self.adapter.cancel_order("pi_1"), "succeeded")

	def test_another_refusal_is_a_gateway_error(self):
		from central.billing.gateways.base import GatewayError

		self.respond(
			400,
			{"error": {"type": "invalid_request_error", "code": "resource_missing", "message": "No such"}},
		)
		with self.assertRaises(GatewayError):
			self.adapter.cancel_setup("seti_missing")
