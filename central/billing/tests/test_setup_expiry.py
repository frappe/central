# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Unfinished card and UPI setups expire after a day, and the team is told once."""

from unittest.mock import MagicMock, patch

import frappe

from central.billing.gateways.base import GatewayTimeout, GatewayUnsupported
from central.billing.payments import mandates, payments, setup_expiry
from central.billing.tests.test_payments import saved_card, stub_adapter
from central.billing.tests.test_paypal_adapter import make_paypal_gateway
from central.billing.tests.test_razorpay_adapter import make_razorpay_gateway
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, ensure_team, run_enqueued_inline

TEAM = "team-setup-expiry"
OTHER_TEAM = "team-setup-expiry-2"
GATEWAY = "Stripe"
NOW = frappe.utils.get_datetime("2026-11-12 12:00:00")
NOTICE = "Your card or UPI setup was not finished, so it was not saved. Add it again from Billing."


def hours_before_now(hours: float, minutes: int = 0):
	return frappe.utils.add_to_date(NOW, hours=-hours, minutes=-minutes)


def gateway_reads(answer=None, error=None):
	"""Stub the gateway the job reads setups from. `answer` is what it says the setup saved."""
	adapter = MagicMock()
	adapter.read_finished_setup.return_value = answer or {}
	adapter.read_finished_setup.side_effect = error
	return patch("central.billing.gateways.registry.get_adapter", return_value=adapter)


class SetupExpiryTestBase(BillingTestCase):
	def setUp(self):
		make_stripe_gateway()
		for team in (TEAM, OTHER_TEAM):
			ensure_team(team)
			frappe.db.delete("Payment Method", {"team": team})
		self.emails = self.enterContext(
			patch(
				"central.notification.engine._fan_out_emails",
				return_value={"queued": 1, "attempted": 1, "failed": 0},
			)
		)

	def tearDown(self):
		# Not swept by the base class, which commits after each test.
		for doctype in ("Team Notification", "Billing Notification Log"):
			frappe.db.delete(doctype, {"team": ["in", [TEAM, OTHER_TEAM]]})
		methods = frappe.get_all("Payment Method", filters={"team": ["in", [TEAM, OTHER_TEAM]]}, pluck="name")
		if methods:
			frappe.db.delete(
				"Comment", {"reference_doctype": "Payment Method", "reference_name": ["in", methods]}
			)

	def make_method(self, status="Pending Validation", started=None, team=TEAM, **fields) -> str:
		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": team,
				"gateway": GATEWAY,
				"method_type": "Card",
				"status": status,
				**fields,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Payment Method", method.name, "creation", started or hours_before_now(25), update_modified=False
		)
		return method.name

	def status(self, name: str) -> str:
		return frappe.db.get_value("Payment Method", name, "status")

	def notices(self, team=TEAM) -> list:
		return frappe.get_all(
			"Team Notification",
			filters={"team": team, "event_type": "payment_method_setup_expired"},
			fields=["title", "message", "reference_name"],
		)


class TestExpiry(SetupExpiryTestBase):
	def test_a_setup_expires_at_24_hours_and_not_before(self):
		fresh = self.make_method(started=hours_before_now(23, minutes=59))
		stale = self.make_method(started=hours_before_now(24))

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(fresh), "Pending Validation")
		self.assertEqual(self.status(stale), "Expired")
		self.assertTrue(
			frappe.db.exists("Billing Event", {"subject": stale, "reason": "setup not finished in time"})
		)

	def test_finished_and_failed_setups_are_left_alone(self):
		active = self.make_method(status="Active", gateway_method_id="pm_active")
		failed = self.make_method(status="Failed")

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(active), "Active")
		self.assertEqual(self.status(failed), "Failed")
		self.assertEqual(self.notices(), [])

	def test_an_expired_setup_is_not_listed_but_an_expired_card_is(self):
		from central.billing.api.dashboard import methods

		setup = self.make_method()
		card = self.make_method(status="Expired", validated_at=hours_before_now(800))

		setup_expiry.expire_unfinished_setups(now=NOW)

		listed = [row["name"] for row in methods.list_payment_methods(TEAM)]
		self.assertEqual(listed, [card])
		self.assertEqual(self.status(setup), "Expired")

	def test_pilot_lists_an_expired_card_but_not_an_expired_setup(self):
		from central.billing.api import billing_api

		setup = self.make_method()
		card = self.make_method(
			status="Expired", gateway_method_id="pm_lapsed", validated_at=hours_before_now(800)
		)

		setup_expiry.expire_unfinished_setups(now=NOW)

		listed = [row["name"] for row in billing_api._payment_method_rows(TEAM)]
		self.assertEqual(listed, [card])
		self.assertEqual(self.status(setup), "Expired")

	def test_a_upi_setup_expires_but_paypal_and_prepaid_rows_are_left_alone(self):
		upi = self.make_method(method_type="UPI Autopay")
		paypal = self.make_method(gateway=make_paypal_gateway().name)
		prepaid = self.make_method(method_type="Prepaid Credits")

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(upi), "Expired")
		self.assertEqual(self.status(paypal), "Pending Validation")
		self.assertEqual(self.status(prepaid), "Pending Validation")

	def test_a_late_confirm_says_the_setup_expired(self):
		setup = self.make_method()
		setup_expiry.expire_unfinished_setups(now=NOW)

		with stub_adapter() as adapter:
			result = payments.confirm_payment_method(setup).get_confirmation()

		adapter.read_saved_card.assert_not_called()
		self.assertEqual(result["status"], "Expired")
		self.assertEqual(result["message"], "This setup expired. Start again to add it.")

	def test_a_lapsed_card_gives_no_setup_message(self):
		card = self.make_method(status="Expired", validated_at=hours_before_now(800))

		result = frappe.get_doc("Payment Method", card).get_confirmation()

		self.assertNotIn("message", result)


class TestGatewayIsAsked(SetupExpiryTestBase):
	def test_a_card_saved_but_never_confirmed_is_detached_and_expired(self):
		setup = self.make_method(setup_reference="seti_done", gateway_customer_id="cus_done")
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = saved_card(payment_method="pm_done", customer="cus_done")

		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch("frappe.enqueue", side_effect=run_enqueued_inline),
		):
			setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(setup), "Expired")
		adapter.remove_saved_method.assert_called_once_with("pm_done", customer_reference="cus_done")
		adapter.charge.assert_not_called()
		adapter.validate_payment_method.assert_not_called()
		self.assertEqual(len(self.notices()), 1)
		self.assertTrue(
			frappe.db.exists(
				"Billing Event",
				{"subject": setup, "reason": "setup saved at the gateway but never confirmed"},
			)
		)

	def test_a_setup_the_gateway_says_unfinished_expires_with_a_notice(self):
		setup = self.make_method(setup_reference="seti_open")

		with gateway_reads({}) as get_adapter:
			setup_expiry.expire_unfinished_setups(now=NOW)

		get_adapter.return_value.read_finished_setup.assert_called_once_with("seti_open")
		self.assertEqual(self.status(setup), "Expired")
		self.assertEqual(len(self.notices()), 1)

	def test_a_setup_with_no_reference_expires_without_a_read(self):
		setup = self.make_method()

		with gateway_reads() as get_adapter:
			setup_expiry.expire_unfinished_setups(now=NOW)

		get_adapter.return_value.read_finished_setup.assert_not_called()
		self.assertEqual(self.status(setup), "Expired")

	def test_a_setup_the_gateway_cannot_read_is_skipped_and_the_sweep_goes_on(self):
		for error in (GatewayTimeout("down"), GatewayUnsupported("no read")):
			unread = self.make_method(setup_reference="seti_unread")
			other = self.make_method(team=OTHER_TEAM)

			with gateway_reads(error=error):
				setup_expiry.expire_unfinished_setups(now=NOW)

			self.assertEqual(self.status(unread), "Pending Validation")
			self.assertEqual(self.status(other), "Expired")
			self.assertEqual(self.notices(), [])
			frappe.db.delete("Payment Method", {"name": ["in", [unread, other]]})


class LateSetupBase(SetupExpiryTestBase):
	def confirm_late(self, confirm, adapter):
		"""Confirm, run the queued release jobs inline, and return the refunds they queued."""
		refunds = []

		def enqueue(method, **kwargs):
			if method.endswith("refund_authorisation_payment"):
				refunds.append(kwargs)
				return None
			return run_enqueued_inline(method, **kwargs)

		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch("frappe.enqueue", side_effect=enqueue),
		):
			result = confirm().get_confirmation()
		return result, refunds


class TestLateConfirm(LateSetupBase):
	def test_a_late_upi_authorisation_is_refunded_and_its_token_cancelled(self):
		make_razorpay_gateway()
		setup = self.make_method(
			status="Expired",
			gateway="Razorpay",
			method_type="UPI Autopay",
			setup_reference="order_late",
			gateway_customer_id="cust_late",
		)
		payment = {
			"id": "pay_late",
			"order_id": "order_late",
			"status": "captured",
			"amount": 100,
			"token_id": "token_late",
			"customer_id": "cust_late",
		}
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = {
			"payment_method": "token_late",
			"customer": "cust_late",
			"payment": payment,
		}
		callback = {
			"razorpay_order_id": "order_late",
			"razorpay_payment_id": "pay_late",
			"razorpay_signature": "s",
		}

		result, refunds = self.confirm_late(lambda: mandates.confirm_mandate(setup, callback), adapter)

		self.assertEqual(result["status"], "Expired")
		self.assertEqual(self.status(setup), "Expired")
		self.assertEqual(
			[(r["payment_id"], r["amount"], r["job_id"]) for r in refunds],
			[("pay_late", 1.0, "mandate-authorisation-refund::pay_late")],
		)
		adapter.remove_saved_method.assert_called_once_with("token_late", customer_reference="cust_late")
		adapter.verify_payment_signature.assert_not_called()

	def test_a_card_saved_after_its_setup_expired_is_detached(self):
		setup = self.make_method(
			status="Expired", setup_reference="seti_late", gateway_customer_id="cus_late"
		)
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = saved_card(payment_method="pm_late", customer="cus_late")

		result, refunds = self.confirm_late(lambda: payments.confirm_payment_method(setup), adapter)

		self.assertEqual(result["status"], "Expired")
		self.assertEqual(result["message"], "This setup expired. Start again to add it.")
		self.assertEqual(refunds, [])
		adapter.read_saved_card.assert_not_called()
		adapter.validate_payment_method.assert_not_called()
		adapter.remove_saved_method.assert_called_once_with("pm_late", customer_reference="cus_late")

	def test_a_late_confirm_on_an_unsaved_setup_removes_nothing(self):
		setup = self.make_method(status="Expired", setup_reference="seti_never")
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = {}

		result, refunds = self.confirm_late(lambda: payments.confirm_payment_method(setup), adapter)

		self.assertEqual(result["status"], "Expired")
		self.assertEqual(refunds, [])
		adapter.remove_saved_method.assert_not_called()

	def test_a_token_another_method_holds_is_kept_but_the_payment_refunded(self):
		make_razorpay_gateway()
		holder = self.make_method(
			status="Active", gateway="Razorpay", method_type="UPI Autopay", gateway_method_id="token_shared"
		)
		setup = self.make_method(
			status="Expired", gateway="Razorpay", method_type="UPI Autopay", setup_reference="order_shared"
		)
		payment = {"id": "pay_shared", "order_id": "order_shared", "status": "captured", "amount": 100}
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = {"payment_method": "token_shared", "payment": payment}

		_result, refunds = self.confirm_late(lambda: mandates.confirm_mandate(setup, {}), adapter)

		adapter.remove_saved_method.assert_not_called()
		self.assertEqual([r["payment_id"] for r in refunds], ["pay_shared"])
		self.assertEqual(self.status(holder), "Active")
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{"reference_name": setup, "content": ["like", "Kept token_shared%"]},
			)
		)

	def test_a_failed_removal_leaves_a_comment_and_fails_the_job(self):
		setup = self.make_method(status="Expired", setup_reference="seti_fail")
		adapter = MagicMock()
		adapter.remove_saved_method.side_effect = GatewayTimeout("down")

		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch("frappe.db.commit"),
		):
			with self.assertRaises(GatewayTimeout):
				setup_expiry.remove_late_saved_method(setup, "pm_fail", "cus_fail")

		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_name": setup,
					"content": ["like", "pm_fail, saved at the gateway%not removed: down"],
				},
			)
		)

	def test_a_lapsed_card_is_never_released(self):
		card = self.make_method(
			status="Expired",
			setup_reference="seti_old",
			gateway_method_id="pm_old",
			validated_at=hours_before_now(800),
		)
		adapter = MagicMock()

		self.confirm_late(lambda: payments.confirm_payment_method(card), adapter)

		adapter.read_finished_setup.assert_not_called()
		adapter.remove_saved_method.assert_not_called()


class TestNotice(SetupExpiryTestBase):
	def test_the_team_is_told_once_in_app_and_by_email(self):
		setup = self.make_method()

		setup_expiry.expire_unfinished_setups(now=NOW)

		notices = self.notices()
		self.assertEqual(len(notices), 1)
		self.assertEqual(notices[0].message, NOTICE)
		self.assertEqual(notices[0].reference_name, setup)
		self.assertEqual(self.emails.call_count, 1)
		log = frappe.get_all(
			"Billing Notification Log",
			filters={"team": TEAM, "event_type": "Payment Method Setup Expired"},
			fields=["message", "status"],
		)
		self.assertEqual(log, [{"message": NOTICE, "status": "Queued"}])

	def test_several_setups_expiring_together_send_one_notice(self):
		self.make_method(started=hours_before_now(30))
		latest = self.make_method(started=hours_before_now(26))

		setup_expiry.expire_unfinished_setups(now=NOW)

		notices = self.notices()
		self.assertEqual(len(notices), 1)
		self.assertEqual(notices[0].reference_name, latest)

	def test_a_second_run_sends_nothing(self):
		self.make_method()

		setup_expiry.expire_unfinished_setups(now=NOW)
		setup_expiry.expire_unfinished_setups(now=frappe.utils.add_to_date(NOW, hours=1))

		self.assertEqual(len(self.notices()), 1)
		self.assertEqual(self.emails.call_count, 1)

	def test_no_notice_when_a_working_method_was_added_after_the_setup(self):
		setup = self.make_method(started=hours_before_now(30))
		self.make_method(status="Active", gateway_method_id="pm_later", validated_at=hours_before_now(29))

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(setup), "Expired")
		self.assertEqual(self.notices(), [])
		self.emails.assert_not_called()

	def test_a_working_method_added_before_the_setup_does_not_stop_the_notice(self):
		self.make_method(status="Active", gateway_method_id="pm_earlier", validated_at=hours_before_now(40))
		self.make_method(started=hours_before_now(30))

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(len(self.notices()), 1)

	def test_one_failing_team_does_not_stop_the_others(self):
		broken = self.make_method()
		other = self.make_method(team=OTHER_TEAM)
		expire_setup = setup_expiry._expire_setup

		def fail_on_broken(name, **kwargs):
			if name == broken:
				raise frappe.ValidationError("broken row")
			return expire_setup(name, **kwargs)

		with patch.object(setup_expiry, "_expire_setup", side_effect=fail_on_broken):
			result = setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(broken), "Pending Validation")
		self.assertEqual(self.status(other), "Expired")
		self.assertEqual(result["expired"], [{"team": OTHER_TEAM, "expired": [other]}])
		self.assertEqual(len(self.notices(OTHER_TEAM)), 1)


class TestNewSetupNeverBlocked(SetupExpiryTestBase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Gateway Customer", {"team": TEAM})

	def test_a_new_setup_starts_and_finishes_while_an_old_one_is_pending(self):
		with stub_adapter(card=saved_card(payment_method="pm_retry")):
			old = payments.initiate_payment_method_setup(TEAM, GATEWAY)["payment_method"]
			new = payments.initiate_payment_method_setup(TEAM, GATEWAY)["payment_method"]
			method = payments.confirm_payment_method(new)

		self.assertEqual(method.status, "Active")
		self.assertEqual(self.status(old), "Cancelled")

	def test_a_saved_but_unconfirmed_card_does_not_block_a_new_setup(self):
		old = self.make_method(started=NOW, gateway_method_id="pm_saved_unconfirmed")
		with stub_adapter(card=saved_card(payment_method="pm_retry")):
			new = payments.initiate_payment_method_setup(TEAM, GATEWAY)["payment_method"]
			method = payments.confirm_payment_method(new)

		self.assertEqual(method.status, "Active")
		self.assertEqual(self.status(old), "Pending Validation")


def setup_payment(**fields) -> dict:
	"""The ₹1 authorisation payment Razorpay takes on a setup order."""
	return {
		"id": "pay_setup",
		"order_id": "order_setup",
		"status": "captured",
		"amount": 100,
		"currency": "INR",
		"token_id": "token_setup",
		"customer_id": "cust_setup",
		"notes": {"team": TEAM},
		**fields,
	}


class RazorpaySetupBase(SetupExpiryTestBase):
	def setUp(self):
		super().setUp()
		make_razorpay_gateway()
		self.adapter = MagicMock()
		self.adapter.read_instrument_fingerprint.return_value = None
		self.refunds = []
		self.enterContext(patch("central.billing.gateways.registry.get_adapter", return_value=self.adapter))
		self.enterContext(patch("frappe.enqueue", side_effect=self.enqueue))

	def enqueue(self, method, **kwargs):
		if method.endswith("refund_authorisation_payment"):
			self.refunds.append(kwargs["payment_id"])
			return None
		return run_enqueued_inline(method, **kwargs)

	def make_mandate_setup(self, **fields) -> str:
		return self.make_method(
			gateway="Razorpay",
			method_type="UPI Autopay",
			setup_reference="order_setup",
			gateway_customer_id="cust_setup",
			**fields,
		)


class TestRazorpaySweep(RazorpaySetupBase):
	def test_a_setup_the_gateway_proves_finished_is_activated(self):
		setup = self.make_mandate_setup()
		self.adapter.read_finished_setup.return_value = {
			"payment_method": "token_setup",
			"customer": "cust_setup",
			"payment": setup_payment(),
		}

		setup_expiry.expire_unfinished_setups(now=NOW)

		method = frappe.get_doc("Payment Method", setup)
		self.assertEqual(method.status, "Active")
		self.assertEqual(method.gateway_method_id, "token_setup")
		self.assertTrue(method.validated_at)
		self.assertEqual(self.refunds, ["pay_setup"])
		self.adapter.remove_saved_method.assert_not_called()
		self.assertEqual(self.notices(), [])

	def test_a_proof_for_another_customer_activates_nothing(self):
		setup = self.make_mandate_setup()
		self.adapter.read_finished_setup.return_value = {
			"payment_method": "token_setup",
			"payment": setup_payment(customer_id="cust_other"),
		}

		setup_expiry.expire_unfinished_setups(now=NOW)

		self.assertEqual(self.status(setup), "Pending Validation")
		self.assertEqual(self.refunds, [])


class TestRazorpaySetupWebhook(RazorpaySetupBase):
	def store_event(self, event_type="payment.captured", **fields) -> str:
		import json

		payment = setup_payment(**fields)
		payload = {"event": event_type, "payload": {"payment": {"entity": payment}}}
		return (
			frappe.get_doc(
				{
					"doctype": "Webhook Event",
					"gateway": "Razorpay",
					"gateway_event_id": f"evt_setup_{frappe.generate_hash(length=8)}",
					"event_type": event_type,
					"raw_payload": json.dumps(payload),
					"status": "Received",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_captured_setup_payment_activates_the_mandate_once(self):
		from central.billing.payments import webhooks

		setup = self.make_mandate_setup(started=hours_before_now(1))
		event = self.store_event()

		webhooks.handle_webhook_event(event)
		second = webhooks.handle_webhook_event(event)
		webhooks.handle_webhook_event(self.store_event())  # a second delivery under a new id

		method = frappe.get_doc("Payment Method", setup)
		self.assertEqual(method.status, "Active")
		self.assertEqual(method.gateway_method_id, "token_setup")
		self.assertEqual(second, {"handled": False, "reason": "already_applied"})
		self.assertEqual(self.refunds, ["pay_setup"])
		self.assertEqual(
			frappe.db.get_value("Webhook Event", event, ["status", "payment_method"]), ("Processed", setup)
		)

	def test_a_payment_that_does_not_match_the_setup_activates_nothing(self):
		from central.billing.payments import webhooks

		setup = self.make_mandate_setup(started=hours_before_now(1))
		for fields in (
			{"notes": {"team": OTHER_TEAM}},
			{"customer_id": "cust_other"},
			{"amount": 50000},
			{"currency": "USD"},
			{"token_id": None},
		):
			webhooks.handle_webhook_event(self.store_event(**fields))

		self.assertEqual(self.status(setup), "Pending Validation")
		self.assertEqual(self.refunds, [])

	def test_an_authorised_payment_waits_for_its_capture(self):
		from central.billing.payments import webhooks

		setup = self.make_mandate_setup(started=hours_before_now(1))
		event = self.store_event(event_type="payment.authorized", status="authorized")

		webhooks.handle_webhook_event(event)

		self.assertEqual(self.status(setup), "Pending Validation")
		self.assertEqual(frappe.db.get_value("Webhook Event", event, "status"), "Ignored")

	def test_a_capture_after_the_setup_expired_is_released(self):
		from central.billing.payments import webhooks

		setup = self.make_mandate_setup(status="Expired")
		self.adapter.read_finished_setup.return_value = {
			"payment_method": "token_setup",
			"customer": "cust_setup",
			"payment": setup_payment(),
		}

		webhooks.handle_webhook_event(self.store_event())

		self.assertEqual(self.status(setup), "Expired")
		self.assertEqual(self.refunds, ["pay_setup"])
		self.adapter.remove_saved_method.assert_called_once_with(
			"token_setup", customer_reference="cust_setup"
		)


class TestReleaseAge(SetupExpiryTestBase):
	def sweep(self, adapter):
		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch("frappe.enqueue", side_effect=run_enqueued_inline),
		):
			setup_expiry.expire_unfinished_setups(now=NOW)

	def test_a_week_old_setup_is_released_whatever_the_gateway_says(self):
		setup = self.make_method(setup_reference="seti_week", started=hours_before_now(24 * 7))
		adapter = MagicMock()
		adapter.read_finished_setup.return_value = {}

		self.sweep(adapter)

		self.assertEqual(self.status(setup), "Expired")
		self.assertEqual(len(self.notices()), 1)
		# Only the release reads the gateway; it found nothing saved to remove.
		adapter.read_finished_setup.assert_called_once_with("seti_week")
		adapter.remove_saved_method.assert_not_called()

	def test_a_setup_the_gateway_cannot_read_waits_a_week_then_is_released(self):
		young = self.make_method(setup_reference="seti_young", started=hours_before_now(24 * 6))
		old = self.make_method(setup_reference="seti_old", started=hours_before_now(24 * 7 + 1))
		adapter = MagicMock()
		adapter.read_finished_setup.side_effect = GatewayTimeout("down")

		self.sweep_queueing_only(adapter)

		self.assertEqual(self.status(young), "Pending Validation")
		self.assertEqual(self.status(old), "Expired")
		self.assertEqual(len(self.notices()), 1)
		# The release is queued for the old row; it reads the gateway in its own job.
		self.assertEqual([kwargs["job_id"] for kwargs in self.queued], [f"late-setup-release::{old}"])

	def sweep_queueing_only(self, adapter):
		queued = []
		with (
			patch("central.billing.gateways.registry.get_adapter", return_value=adapter),
			patch("frappe.enqueue", side_effect=lambda method, **kwargs: queued.append(kwargs)),
		):
			setup_expiry.expire_unfinished_setups(now=NOW)
		self.queued = queued

	def test_rows_the_gateway_cannot_read_do_not_starve_the_rest(self):
		stuck = [
			self.make_method(setup_reference=f"seti_stuck_{i}", started=hours_before_now(30 + i))
			for i in range(3)
		]
		old = self.make_method(setup_reference="seti_old", started=hours_before_now(24 * 8))
		adapter = MagicMock()
		adapter.read_finished_setup.side_effect = GatewayTimeout("down")

		with patch.object(setup_expiry, "SETUPS_PER_RUN", 3):
			self.sweep_queueing_only(adapter)

		self.assertEqual(self.status(old), "Expired")
		self.assertEqual([self.status(name) for name in stuck], ["Pending Validation"] * 3)
		self.assertEqual([kwargs["payment_method"] for kwargs in self.queued], [old])
