# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from datetime import timedelta
from unittest.mock import MagicMock, patch

import frappe

from central.billing.doctype.top_up_order.top_up_order import TopupOrder
from central.billing.payments import mandates, payments, setup_lockout
from central.billing.platform.records import save_billing_record
from central.billing.states import transition
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import (
	BillingTestCase,
	complete_billing_profile,
	ensure_team,
	make_billing_team,
	make_user,
	run_enqueued_inline,
)

TEAM = "team-lockout"
OTHER_TEAM = "team-lockout-other"
THIRD_TEAM = "team-lockout-third"
DECLINED = {"failure_code": "card_declined", "decline_code": "do_not_honor"}
MINUTE = 60
HOUR = 60 * MINUTE


class TestSetupLockout(BillingTestCase):
	def setUp(self):
		for team in (TEAM, OTHER_TEAM, THIRD_TEAM):
			ensure_team(team)
		complete_billing_profile(TEAM)
		make_stripe_gateway()
		self.user = make_user("lockout-user@example.com")
		self.enqueue = patch("frappe.enqueue", side_effect=run_enqueued_inline)
		self.enqueue.start()
		self.addCleanup(self.enqueue.stop)
		self.notify = patch("central.billing.platform.alerts.notify_operators", return_value=["Email"])
		self.sent = self.notify.start()
		self.addCleanup(self.notify.stop)

	def record_failures(self, times=1, team=TEAM, user=None, failure=None, ago=timedelta(0)):
		"""Record failed setups on a new pending method, each `ago` before now."""
		method = self.pending_method(team, user)
		for _ in range(times):
			payments._record_setup_failure(method, failure or DECLINED)
			self.backdate(method, ago)
		return method

	def pending_method(self, team=TEAM, user=None) -> str:
		method = frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": team,
				"gateway": "Stripe",
				"method_type": "Card",
				"status": "Pending Validation",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Payment Method", method.name, "owner", user or "Administrator")
		return method.name

	def paid_top_up(self, team=TEAM, user=None) -> str:
		"""A top-up moved to Credited now, as `credit_wallet` moves it."""
		order = frappe.get_doc(
			{"doctype": "Top-up Order", "team": team, "gateway": "Stripe", "currency": "INR", "total": 500}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Top-up Order", order.name, "owner", user or "Administrator")
		order.reload()
		transition(order, "Credited", actor="gateway", correlation=team, amount=order.total)
		save_billing_record(order)
		return order.name

	def backdate(self, subject, ago):
		latest = frappe.get_all(
			"Billing Event", {"subject": subject}, pluck="name", order_by="creation desc", limit=1
		)[0]
		frappe.db.set_value(
			"Billing Event", latest, "occurred_at", frappe.utils.now_datetime() - ago, update_modified=False
		)

	def assert_wait(self, seconds, team=TEAM, user=None):
		wait = setup_lockout.wait_for(team, user)
		if seconds is None:
			self.assertIsNone(wait)
			return
		self.assertAlmostEqual(wait.total_seconds(), seconds, delta=MINUTE)

	def test_the_wait_follows_the_schedule(self):
		expected = {
			1: None,
			4: None,
			5: 10 * MINUTE,
			6: 10 * MINUTE,
			7: 30 * MINUTE,
			8: 2 * HOUR,
			9: 6 * HOUR,
			10: 24 * HOUR,
			12: 24 * HOUR,
		}
		method = self.pending_method()
		for failures in range(1, 13):
			payments._record_setup_failure(method, DECLINED)
			if failures in expected:
				self.assert_wait(expected[failures])

	def test_the_wait_counts_from_the_latest_failure(self):
		self.record_failures(times=5, ago=timedelta(minutes=4))
		self.assert_wait(6 * MINUTE)
		frappe.db.set_value(
			"Billing Event", {"team": TEAM}, "occurred_at", frappe.utils.add_to_date(None, minutes=-11)
		)
		self.assert_wait(None)

	def test_one_user_is_counted_across_teams(self):
		self.record_failures(times=3, team=TEAM, user=self.user)
		self.record_failures(times=2, team=OTHER_TEAM, user=self.user)
		self.assert_wait(10 * MINUTE, team=THIRD_TEAM, user=self.user)
		self.assert_wait(None, team=THIRD_TEAM)
		self.assert_wait(None, team=TEAM)

	def test_one_team_is_counted_across_users(self):
		for _ in range(5):
			self.record_failures(user=make_user())
		self.assert_wait(10 * MINUTE, user=make_user("lockout-newcomer@example.com"))

	def test_only_bank_refusals_count(self):
		not_counted = (
			{"failure_code": "setup_intent_authentication_failure"},
			{"failure_code": "authentication_abandoned"},
			{"failure_code": "BAD_REQUEST_ERROR", "decline_code": "payment_cancelled"},
			{"failure_code": "canceled"},
			{"failure_code": "customer_mismatch"},
			{"failure_code": "gateway_timeout"},
			{"failure_code": "timeout"},
			{"failure_code": "setup_failed"},
		)
		for failure in not_counted:
			self.record_failures(failure=failure)
		self.assert_wait(None)

		for _ in range(5):
			self.record_failures(
				failure={"failure_code": "BAD_REQUEST_ERROR", "decline_code": "authentication_failed"}
			)
		self.assert_wait(10 * MINUTE)

	def test_bank_refusals_are_told_from_temporary_declines(self):
		from central.billing.payments.decline import is_bank_refusal

		cases = {
			("card_declined", None): True,
			("card_declined", "do_not_honor"): True,
			("card_declined", "insufficient_funds"): True,
			("card_declined", "issuer_not_available"): False,
			("card_declined", "try_again_later"): False,
			("card_declined", "processing_error"): False,
			("card_declined", "reenter_transaction"): False,
			("card_declined", "approve_with_id"): False,
			("incorrect_zip", None): True,
			("payment_method_provider_decline", None): True,
			("BAD_REQUEST_ERROR", "payment_failed"): True,
			("BAD_REQUEST_ERROR", "authentication_failed"): True,
			("BAD_REQUEST_ERROR", "payment_cancelled"): False,
			("processing_error", None): False,
			# Our own fallback when a gateway gave no code; Razorpay sends its reason as the decline code.
			("payment_failed", None): False,
		}
		for (code, reason), expected in cases.items():
			self.assertEqual(is_bank_refusal(code, reason), expected, (code, reason))

	def test_a_bank_that_asks_for_a_retry_does_not_lock(self):
		self.record_failures(
			times=5, failure={"failure_code": "card_declined", "decline_code": "try_again_later"}
		)
		self.assert_wait(None)
		self.record_failures(times=5, failure={"failure_code": "card_declined"})
		self.assert_wait(10 * MINUTE)

	def test_an_expired_or_cancelled_setup_does_not_count(self):
		for _ in range(5):
			method = frappe.get_doc("Payment Method", self.pending_method())
			payments.transition(method, "Cancelled", reason="setup abandoned")
			method.save(ignore_permissions=True)
		self.assert_wait(None)

	def test_a_failed_card_check_counts_but_a_customer_mismatch_does_not(self):
		for _ in range(5):
			payments._fail_method(
				frappe.get_doc("Payment Method", self.pending_method()), {"failure_code": "customer_mismatch"}
			)
		self.assert_wait(None)
		for _ in range(5):
			payments._fail_method(frappe.get_doc("Payment Method", self.pending_method()), DECLINED)
		self.assert_wait(10 * MINUTE)

	def test_a_card_check_the_bank_asks_to_retry_does_not_count(self):
		for reason in ("try_again_later", "issuer_not_available"):
			for _ in range(3):
				method = frappe.get_doc("Payment Method", self.pending_method())
				payments._fail_method(method, {"failure_code": "card_declined", "decline_code": reason})
		self.assert_wait(None)

	def test_a_working_method_for_the_team_resets_the_count(self):
		self.record_failures(times=5)
		frappe.db.set_value(
			"Payment Method", self.pending_method(), "validated_at", frappe.utils.now_datetime()
		)
		self.assert_wait(None)

	def test_a_method_the_user_added_resets_their_count(self):
		self.record_failures(times=5, team=OTHER_TEAM, user=self.user)
		self.assert_wait(10 * MINUTE, team=THIRD_TEAM, user=self.user)
		someone_else = self.pending_method(THIRD_TEAM, make_user())
		frappe.db.set_value("Payment Method", someone_else, "validated_at", frappe.utils.now_datetime())
		self.assert_wait(10 * MINUTE, team=THIRD_TEAM, user=self.user)
		theirs = self.pending_method(THIRD_TEAM, self.user)
		frappe.db.set_value("Payment Method", theirs, "validated_at", frappe.utils.now_datetime())
		self.assert_wait(None, team=THIRD_TEAM, user=self.user)

	def test_a_method_proven_before_the_failures_does_not_reset(self):
		proven = self.pending_method()
		frappe.db.set_value(
			"Payment Method", proven, "validated_at", frappe.utils.add_to_date(None, hours=-1)
		)
		self.record_failures(times=5)
		self.assert_wait(10 * MINUTE)

	def test_seven_quiet_days_reset_the_count(self):
		self.record_failures(times=4, ago=timedelta(days=8))
		self.record_failures(times=1)
		self.assert_wait(None)

	def test_failures_less_than_seven_days_apart_stay_in_one_run(self):
		for days_ago in (24, 18, 12, 6, 0):
			self.record_failures(ago=timedelta(days=days_ago))
		self.assert_wait(10 * MINUTE)

	def test_an_operator_clears_the_lock(self):
		from central.billing.api.admin.teams import clear_setup_lock

		self.record_failures(times=10)
		self.assert_wait(24 * HOUR)
		clear_setup_lock(TEAM)
		self.assert_wait(None)
		self.assertTrue(frappe.db.exists("Billing Event", {"team": TEAM, "event_type": "Setup Lock Cleared"}))

		self.record_failures(times=5)
		self.assert_wait(10 * MINUTE)

	def test_only_an_operator_can_clear_the_lock(self):
		from central.billing.api.admin.teams import clear_setup_lock

		self.record_failures(times=10)
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			clear_setup_lock(TEAM)
		frappe.set_user("Administrator")
		self.assert_wait(24 * HOUR)

	def test_a_locked_team_cannot_start_a_setup(self):
		self.record_failures(times=5)
		adapter = MagicMock()
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(setup_lockout.TooManyFailedSetups):
				payments.initiate_payment_method_setup(TEAM, "Stripe")
			with self.assertRaises(setup_lockout.TooManyFailedSetups):
				mandates.setup_mandate(TEAM, "Stripe")
			with self.assertRaises(setup_lockout.TooManyFailedSetups):
				mandates.setup_card(TEAM, "Stripe")
		adapter.setup_payment_method.assert_not_called()

	def test_a_locked_team_cannot_top_up(self):
		self.record_failures(times=5)
		with self.assertRaises(setup_lockout.TooManyFailedSetups):
			TopupOrder.start(TEAM, "Stripe", "INR", 500)

	def test_a_locked_team_top_up_makes_no_gateway_call(self):
		from central.billing.api import dashboard

		self.record_failures(times=5)
		adapter = MagicMock()
		with patch("central.billing.gateways.registry.get_adapter", return_value=adapter):
			with self.assertRaises(setup_lockout.TooManyFailedSetups):
				dashboard.create_topup_order(team=TEAM, amount=500)
		adapter.create_customer.assert_not_called()

	def test_declined_top_ups_count(self):
		order = TopupOrder.start(TEAM, "Stripe", "INR", 500)
		for attempt in range(5):
			order.record_decline(
				{"failure_code": "BAD_REQUEST_ERROR", "decline_code": "insufficient_balance"},
				f"evt_lock_{attempt}",
			)
		self.assert_wait(10 * MINUTE)

	def test_operators_are_alerted_once_on_the_tenth_failure(self):
		self.record_failures(times=9)
		self.sent.assert_not_called()
		self.record_failures(times=1)
		self.sent.assert_called_once()
		self.assertEqual(self.sent.call_args.args[1][0]["subject"], TEAM)
		self.record_failures(times=2)
		self.sent.assert_called_once()

	def test_the_message_names_the_exact_wait(self):
		expected = {
			timedelta(seconds=20): "1 minute",
			timedelta(minutes=1): "1 minute",
			timedelta(minutes=27, seconds=10): "28 minutes",
			timedelta(minutes=59): "59 minutes",
			timedelta(minutes=59, seconds=1): "1 hour",
			timedelta(minutes=60): "1 hour",
			timedelta(minutes=61): "1 hour 1 minute",
			timedelta(minutes=65): "1 hour 5 minutes",
			timedelta(minutes=120): "2 hours",
			timedelta(minutes=121): "2 hours 1 minute",
			timedelta(minutes=125): "2 hours 5 minutes",
			timedelta(minutes=360): "6 hours",
			timedelta(hours=24): "24 hours",
		}
		for wait, duration in expected.items():
			self.assertEqual(
				setup_lockout.wait_message(wait), f"Too many failed attempts. Try again in {duration}."
			)

	def test_a_paid_top_up_resets_the_team_count(self):
		self.record_failures(times=5)
		self.paid_top_up()
		self.assert_wait(None)

	def test_a_top_up_paid_before_the_failures_does_not_reset(self):
		order = self.paid_top_up()
		self.backdate(order, timedelta(hours=1))
		self.record_failures(times=5)
		self.assert_wait(10 * MINUTE)

	def test_a_top_up_the_user_paid_resets_their_count(self):
		self.record_failures(times=5, team=OTHER_TEAM, user=self.user)
		self.paid_top_up(THIRD_TEAM, self.user)
		self.assert_wait(None, team=TEAM, user=self.user)

	def test_another_users_top_up_resets_the_team_but_not_the_user(self):
		self.record_failures(times=3, team=TEAM, user=self.user)
		self.record_failures(times=2, team=OTHER_TEAM, user=self.user)
		self.record_failures(times=2, team=TEAM, user=make_user())
		self.assert_wait(10 * MINUTE, team=TEAM)
		self.paid_top_up(TEAM, make_user())
		self.assert_wait(None, team=TEAM)
		self.assert_wait(10 * MINUTE, team=THIRD_TEAM, user=self.user)
		self.assert_wait(10 * MINUTE, team=TEAM, user=self.user)

	def test_a_relock_within_a_day_does_not_alert_again(self):
		from central.billing.api.admin.teams import clear_setup_lock

		self.record_failures(times=10)
		clear_setup_lock(TEAM)
		self.record_failures(times=10)
		self.sent.assert_called_once()

		alerted = {"team": TEAM, "event_type": setup_lockout.ALERTED_EVENT}
		frappe.db.set_value(
			"Billing Event", alerted, "occurred_at", frappe.utils.add_to_date(None, hours=-25)
		)
		clear_setup_lock(TEAM)
		self.record_failures(times=10)
		self.assertEqual(self.sent.call_count, 2)

	def test_the_team_alert_says_who_how_many_how_long_and_how_to_clear(self):
		self.record_failures(times=10)
		detail = self.sent.call_args.args[1][0]["detail"]
		self.assertRegex(
			detail,
			rf"^Team {TEAM} \({TEAM}\) had 10 failed attempts in a row\. They must wait 24h, "
			rf"until \d{{2}} \w{{3}} \d{{4}} \d{{2}}:\d{{2}} {frappe.utils.get_system_timezone()}\. "
			r"To let them try now, open the Billing Profile and click Clear Setup Lock\.$",
		)
		self.assertNotIn("do_not_honor", detail)

	def test_the_user_alert_names_the_user(self):
		self.record_failures(times=5, team=OTHER_TEAM, user=self.user)
		self.record_failures(times=5, team=THIRD_TEAM, user=self.user)
		self.sent.assert_called_once()
		alert = self.sent.call_args.args[1][0]
		self.assertEqual(alert["team"], THIRD_TEAM)
		self.assertTrue(
			alert["detail"].startswith(
				f"User {self.user} had 10 failed attempts in a row across their teams, "
				f"the latest in team {THIRD_TEAM} ({THIRD_TEAM}). They must wait 24h"
			)
		)
		self.assertTrue(alert["detail"].endswith("The clear lets them try again in this team only."))

	def test_the_clear_button_shows_while_a_member_waits(self):
		team = make_billing_team(self.user).name
		self.assertFalse(setup_lockout.is_anyone_waiting(team))
		self.record_failures(times=5, team=OTHER_TEAM, user=self.user)
		self.assertTrue(setup_lockout.is_anyone_waiting(team))

	def test_only_an_operator_is_offered_the_clear(self):
		self.record_failures(times=5)
		profile = frappe.get_doc("Billing Profile", TEAM)
		profile.run_method("onload")
		self.assertTrue(profile.get_onload().setup_lock_wait)

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		profile.run_method("onload")
		self.assertFalse(profile.get_onload().setup_lock_wait)

	def test_the_refusal_carries_the_wait(self):
		self.record_failures(times=7)
		with self.assertRaises(setup_lockout.TooManyFailedSetups) as raised:
			setup_lockout.check(TEAM)
		self.assertIn("Try again in 30 minutes", str(raised.exception))

	def test_the_dashboard_reads_the_wait_without_opening_anything(self):
		from central.billing.api.dashboard import get_setup_wait

		team = make_billing_team(self.user).name
		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(get_setup_wait(team), {"message": None, "seconds": None})
		frappe.set_user("Administrator")
		self.record_failures(times=5, team=team)
		frappe.set_user(self.user)
		wait = get_setup_wait(team)
		self.assertIn("Try again in 10 minutes", wait["message"])
		self.assertAlmostEqual(wait["seconds"], 10 * MINUTE, delta=MINUTE)
		self.assertFalse(frappe.db.exists("Top-up Order", {"team": team}))
		self.assertEqual(frappe.db.count("Payment Method", {"team": team}), 1)

	def test_the_dashboard_wait_refuses_another_team(self):
		from central.billing.api.dashboard import get_setup_wait

		frappe.set_user(self.user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			get_setup_wait(TEAM)
