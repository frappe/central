# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Unfinished card and UPI setups expire after a day, and the team is told once."""

from unittest.mock import patch

import frappe

from central.billing.payments import payments, setup_expiry
from central.billing.tests.test_payments import saved_card, stub_adapter
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, ensure_team

TEAM = "team-setup-expiry"
OTHER_TEAM = "team-setup-expiry-2"
GATEWAY = "Stripe"
NOW = frappe.utils.get_datetime("2026-11-12 12:00:00")
NOTICE = "Your card or UPI setup was not finished, so it was not saved. Add it again from Billing."


def hours_before_now(hours: float, minutes: int = 0):
	return frappe.utils.add_to_date(NOW, hours=-hours, minutes=-minutes)


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

		def fail_on_broken(name):
			if name == broken:
				raise frappe.ValidationError("broken row")
			return expire_setup(name)

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
