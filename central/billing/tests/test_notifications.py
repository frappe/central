# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification suite — sole sender (issue #20)."""

from unittest.mock import patch

import frappe

from central.billing.payments import settlement
from central.billing.platform import notifications
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team

TEAM = "team-notify"


class NotificationTestBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		self._purge()
		self.enterContext(
			patch(
				"central.notification.engine._fan_out_emails",
				return_value={"queued": 1, "attempted": 1, "failed": 0},
			)
		)

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Billing Notification Log", {"team": TEAM})
		frappe.db.delete("Team Notification", {"team": TEAM})
		frappe.db.delete("Credit Ledger Entry", {"team": TEAM})
		frappe.db.delete("Credit Wallet", {"team": TEAM})
		frappe.db.commit()

	def _logs(self, event_type=None):
		filters = {"team": TEAM}
		if event_type:
			filters["event_type"] = event_type
		return frappe.get_all("Billing Notification Log", filters, ["event_type", "status", "message"])


class TestNotify(NotificationTestBase):
	def test_default_sends_and_logs(self):
		out = notifications.notify(TEAM, "Payment Success", context={"invoice": "INV-1"})
		self.assertTrue(out["notified"])
		logs = self._logs("Payment Success")
		self.assertEqual(logs[0]["status"], "Queued")
		self.assertIn("INV-1", logs[0]["message"])

	def test_template_renders_with_context(self):
		notifications.notify(TEAM, "Payment Failure", context={"invoice": "INV-2", "reason": "card_declined"})
		msg = self._logs("Payment Failure")[0]["message"]
		self.assertIn("INV-2", msg)
		self.assertIn("card_declined", msg)

	def test_explicit_message_overrides_template(self):
		notifications.notify(TEAM, "Payment Success", message="Custom paid message")
		self.assertEqual(self._logs("Payment Success")[0]["message"], "Custom paid message")

	def test_always_sends_and_logs(self):
		out = notifications.notify(TEAM, "Payment Retry", context={"invoice": "INV-3", "reason": "x"})
		self.assertTrue(out["notified"])
		log = self._logs("Payment Retry")[0]
		self.assertEqual(log["status"], "Queued")

	def test_email_log_records_queued_instead_of_sent(self):
		with patch(
			"central.notification.engine._fan_out_emails",
			return_value={"queued": 1, "attempted": 1, "failed": 0},
		):
			out = notifications.notify(TEAM, "Payment Success")

		self.assertEqual(out["email_status"], "Queued")
		self.assertEqual(self._logs("Payment Success")[0]["status"], "Queued")

	def test_email_log_records_failed_queueing(self):
		with patch(
			"central.notification.engine._fan_out_emails",
			return_value={"queued": 0, "attempted": 1, "failed": 1},
		):
			out = notifications.notify(TEAM, "Payment Failure")

		self.assertEqual(out["email_status"], "Failed")
		self.assertEqual(self._logs("Payment Failure")[0]["status"], "Failed")


class TestWiredEvents(NotificationTestBase):
	def test_credit_low_uses_forecast_threshold(self):
		from central.billing.revenue import credits

		credits.purchase(TEAM, 100, "INR")
		# Projected spend at 80% of balance → the credit_low notification fires.
		settlement.credit_forecast(TEAM, 80, notify=True)
		self.assertTrue(self._logs("Credit Low"))

	def test_credit_low_does_not_fire_below_threshold(self):
		from central.billing.revenue import credits

		credits.purchase(TEAM, 100, "INR")
		settlement.credit_forecast(TEAM, 50, notify=True)
		self.assertFalse(self._logs("Credit Low"))
