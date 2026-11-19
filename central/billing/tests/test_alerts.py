# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Operator alerts fire on what the sweeps cannot fix, and stay quiet otherwise."""

import inspect
import re
from unittest.mock import patch

import frappe
import requests

from central.billing.platform import alerts, invariants, kinds
from central.billing.tests.test_reconciliation import ReconTestBase
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase, billing_settings

RAVEN = {
	"raven_site_url": "https://raven.example.com/",
	"raven_channel_id": "billing-alerts",
	"raven_api_key": "bot-key",
	"raven_api_secret": "bot-secret",
}
ALERT = {"alert": "invariant", "subject": "INV-1", "team": "t1", "detail": "C2: drift"}


class TestOperatorAlerts(BillingTestCase):
	def setUp(self):
		frappe.cache().delete_value(alerts._CACHE_KEY)
		self.mail = patch.object(alerts.frappe, "sendmail").start()
		self.raven = patch.object(alerts.requests, "post").start()
		self.addCleanup(patch.stopall)
		self.gateway = make_stripe_gateway().name
		self.enterContext(
			billing_settings(operator_alert_channel="Email", operator_alert_emails="ops@example.com")
		)

	def _quiet_sources(self, *live):
		"""Run the alert job with only the named sources live."""
		return patch.object(alerts, "SOURCES", live)

	def test_a_clean_system_pages_nobody(self):
		with self._quiet_sources(lambda: []):
			result = alerts.run_operator_alerts()
		self.assertEqual(result, {"alerts": 0, "muted": 0, "notified": False})
		self.mail.assert_not_called()

	def test_an_open_alert_mails_the_named_addresses(self):
		with self._quiet_sources(lambda: [ALERT]):
			result = alerts.run_operator_alerts()

		self.assertEqual(result["alerts"], 1)
		self.assertEqual(result["sent_to"], ["Email"])
		self.assertEqual(self.mail.call_args.kwargs["recipients"], ["ops@example.com"])
		self.assertIn("1 invariant", self.mail.call_args.kwargs["subject"])
		self.raven.assert_not_called()

	def test_the_same_digest_is_not_mailed_twice_in_the_window(self):
		alert = {"alert": "invariant", "subject": "INV-1", "team": "t1", "detail": "C2: drift"}
		with self._quiet_sources(lambda: [alert]):
			alerts.run_operator_alerts()
			second = alerts.run_operator_alerts()

		self.assertFalse(second["notified"])
		self.assertEqual(self.mail.call_count, 1)

	def test_a_new_kind_of_trouble_breaks_through_the_suppression(self):
		first = {"alert": "invariant", "subject": "INV-1", "team": None, "detail": "drift"}
		second = {"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}
		with self._quiet_sources(lambda: [first]):
			alerts.run_operator_alerts()
		with self._quiet_sources(lambda: [first, second]):
			alerts.run_operator_alerts()

		self.assertEqual(self.mail.call_count, 2)

	def test_clearing_the_trouble_re_arms_the_alert(self):
		alert = {"alert": "invariant", "subject": "INV-1", "team": None, "detail": "drift"}
		with self._quiet_sources(lambda: [alert]):
			alerts.run_operator_alerts()
		with self._quiet_sources(lambda: []):
			alerts.run_operator_alerts()
		with self._quiet_sources(lambda: [alert]):
			alerts.run_operator_alerts()

		self.assertEqual(self.mail.call_count, 2)

	def _mute(self, *rows):
		"""Mute alerts in Billing Settings for this test: (category, alert, until) rows."""
		table = [
			{"category": category, "alert": alert, "until": until, "reason": "known issue"}
			for category, alert, until in rows
		]
		return billing_settings(muted_operator_alerts=table)

	def test_a_muted_category_mutes_every_alert_in_it(self):
		webhook = {"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}
		refund = {"alert": "failed_refund", "subject": "INV-2", "team": "t1", "detail": "refused"}
		with self._quiet_sources(lambda: [webhook, refund, ALERT]), self._mute(("Payments", None, None)):
			result = alerts.run_operator_alerts()

		self.assertEqual((result["alerts"], result["muted"]), (1, 2))
		self.assertIn("1 invariant", self.mail.call_args.kwargs["subject"])

	def test_a_muted_alert_leaves_the_rest_of_its_category(self):
		webhook = {"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}
		refund = {"alert": "failed_refund", "subject": "INV-2", "team": "t1", "detail": "refused"}
		with self._quiet_sources(lambda: [webhook, refund]), self._mute(("Payments", "Failed webhook", None)):
			result = alerts.run_operator_alerts()

		self.assertEqual((result["alerts"], result["muted"]), (1, 1))
		self.assertIn("1 failed_refund", self.mail.call_args.kwargs["subject"])

	def test_a_muted_check_silences_only_that_check(self):
		b8 = {"alert": "readiness", "check": "B8", "subject": "t1", "team": "t1", "detail": "B8: no profile"}
		b1 = {"alert": "readiness", "check": "B1", "subject": "t2", "team": "t2", "detail": "B1: currency"}
		b8_option = "B8 · Billed Indian teams have a Tax Profile"
		with self._quiet_sources(lambda: [b8, b1]), self._mute(("Readiness checks", b8_option, None)):
			result = alerts.run_operator_alerts()

		self.assertEqual((result["alerts"], result["muted"]), (1, 1))
		self.assertIn("t2", self.mail.call_args.kwargs["args"]["groups"][0]["rows"][0][0])

	def test_a_mute_that_has_ended_lets_the_alert_through(self):
		ended = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)
		with self._quiet_sources(lambda: [ALERT]), self._mute(("Money checks", None, ended)):
			result = alerts.run_operator_alerts()

		self.assertEqual(result["muted"], 0)
		self.assertEqual(self.mail.call_count, 1)

	def test_a_mute_with_an_end_time_ahead_holds(self):
		ahead = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=1)
		with self._quiet_sources(lambda: [ALERT]), self._mute(("Money checks", None, ahead)):
			alerts.run_operator_alerts()

		self.mail.assert_not_called()

	def test_an_alert_from_another_category_is_refused(self):
		with self.assertRaises(frappe.ValidationError), self._mute(("Invoicing", "Failed webhook", None)):
			pass

	def test_every_alert_kind_has_a_category(self):
		# Read the kinds from the sources, so a new source cannot be left out of the list.
		sent = set(re.findall(r'"alert": "([a-z_]+)"', inspect.getsource(alerts)))
		categorised = {kind for group in kinds.CATEGORIES.values() for kind in group}
		self.assertEqual(sent, categorised)

	def test_one_broken_source_does_not_blind_the_others(self):
		def broken():
			raise RuntimeError("source down")

		alert = {"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}
		with self._quiet_sources(broken, lambda: [alert]):
			self.assertEqual([found["subject"] for found in alerts.collect()], ["WH-1"])

	def test_a_failed_webhook_older_than_the_window_is_an_alert(self):
		event = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": frappe.generate_hash(length=10),
				"event_type": "payment_intent.succeeded",
				"status": "Failed",
				"error": "adapter blew up",
			}
		).insert(ignore_permissions=True)
		old = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-2)
		frappe.db.set_value("Webhook Event", event.name, "creation", old, update_modified=False)

		found = [a for a in alerts.failed_webhooks() if a["subject"] == event.name]
		self.assertEqual(len(found), 1)
		self.assertIn("adapter blew up", found[0]["detail"])

	def test_a_webhook_that_failed_moments_ago_is_left_alone(self):
		frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": self.gateway,
				"gateway_event_id": frappe.generate_hash(length=10),
				"event_type": "payment_intent.succeeded",
				"status": "Failed",
				"error": "still retrying",
			}
		).insert(ignore_permissions=True)
		self.assertEqual([a for a in alerts.failed_webhooks() if "still retrying" in a["detail"]], [])


class TestOperatorAlertDelivery(BillingTestCase):
	def setUp(self):
		self.mail = patch.object(alerts.frappe, "sendmail").start()
		self.raven = patch.object(alerts.requests, "post").start()
		self.addCleanup(patch.stopall)

	def _settings(self, channel, emails="ops@example.com", **raven):
		return billing_settings(operator_alert_channel=channel, operator_alert_emails=emails, **raven)

	def test_the_raven_channel_posts_once_and_sends_no_email(self):
		with self._settings("Raven", **RAVEN):
			sent_to = alerts.notify_operators("Billing needs attention", [ALERT])

		self.assertEqual(sent_to, ["Raven"])
		self.mail.assert_not_called()
		self.raven.assert_called_once()
		call = self.raven.call_args
		self.assertEqual(call.args[0], "https://raven.example.com" + alerts.RAVEN_SEND_PATH)
		self.assertEqual(call.kwargs["headers"]["Authorization"], "token bot-key:bot-secret")
		self.assertEqual(call.kwargs["json"]["channel_id"], "billing-alerts")

	def test_a_failed_raven_post_falls_back_to_email_once(self):
		self.raven.side_effect = requests.ConnectionError("raven down")
		with self._settings("Raven", **RAVEN):
			sent_to = alerts.notify_operators("Billing needs attention", [ALERT])

		self.assertEqual(sent_to, ["Email"])
		self.mail.assert_called_once()

	def test_an_unconfigured_raven_falls_back_to_email(self):
		with self._settings("Raven"):
			sent_to = alerts.notify_operators("Billing needs attention", [ALERT])

		self.assertEqual(sent_to, ["Email"])
		self.raven.assert_not_called()

	def test_both_channels_get_the_alert_once(self):
		with self._settings("Raven and Email", **RAVEN):
			sent_to = alerts.notify_operators("Billing needs attention", [ALERT])

		self.assertEqual(sent_to, ["Raven", "Email"])
		self.assertEqual((self.raven.call_count, self.mail.call_count), (1, 1))

	def test_the_email_channel_never_posts_to_raven(self):
		with self._settings("Email", **RAVEN):
			sent_to = alerts.notify_operators("Billing needs attention", [ALERT])

		self.assertEqual(sent_to, ["Email"])
		self.raven.assert_not_called()

	def test_gateway_error_text_is_escaped_in_the_raven_message(self):
		alert = {**ALERT, "detail": "<script>alert(1)</script>"}
		with self._settings("Raven", **RAVEN):
			alerts.notify_operators("Billing needs attention", [alert])

		text = self.raven.call_args.kwargs["json"]["text"]
		self.assertNotIn("<script>", text)
		self.assertIn("&lt;script&gt;", text)

	def test_a_check_alert_says_what_the_check_expected(self):
		b8 = invariants.Violation(
			check="B8", detail="no profile", team="t1", subject_doctype="Team", subject="t1"
		)
		with (
			self._settings("Raven", **RAVEN),
			patch.object(alerts, "SOURCES", (alerts.readiness_gaps,)),
			patch.object(alerts.invariants, "audit", return_value=[b8]),
		):
			alerts.notify_operators("Billing needs attention", alerts.collect())

		text = self.raven.call_args.kwargs["json"]["text"]
		self.assertIn("B8 · Billed Indian teams have a Tax Profile", text)
		self.assertIn("Expected: A billed Indian team with no Tax Profile pays default GST", text)

	def test_a_plain_alert_says_what_its_kind_means(self):
		def failed_webhooks():
			"""Webhooks that failed to process and have not been retried since."""
			return [{"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}]

		with self._settings("Raven", **RAVEN), patch.object(alerts, "SOURCES", (failed_webhooks,)):
			alerts.notify_operators("Billing needs attention", alerts.collect())

		text = self.raven.call_args.kwargs["json"]["text"]
		self.assertIn("<strong>Failed webhook</strong> (1)", text)
		self.assertIn("Webhooks that failed to process and have not been retried since.", text)

	def test_a_channel_with_email_needs_an_address(self):
		with self.assertRaises(frappe.ValidationError), self._settings("Raven and Email", emails=""):
			pass

	def test_an_invalid_address_is_refused(self):
		with self.assertRaises(frappe.ValidationError), self._settings("Email", emails="not-an-email"):
			pass


class TestOperatorAlertSources(ReconTestBase):
	def test_a_capture_on_an_unpaid_invoice_a_day_later_is_an_alert(self):
		invoice = self._open_invoice()
		attempt = self._captured_attempt(invoice, minutes_old=alerts.ATTEMPT_STALE_HOURS * 60 + 5)

		found = [a for a in alerts.unsettled_captures() if a["subject"] == attempt]
		self.assertEqual(len(found), 1)
		self.assertIn(invoice, found[0]["detail"])

	def test_a_recent_capture_is_left_to_reconciliation(self):
		attempt = self._captured_attempt(self._open_invoice(), minutes_old=60)
		self.assertFalse([a for a in alerts.unsettled_captures() if a["subject"] == attempt])

	def test_a_debit_the_gateway_still_holds_is_not_stale(self):
		attempt = self._captured_attempt(
			self._open_invoice(), minutes_old=alerts.ATTEMPT_STALE_HOURS * 60 + 5
		)
		hold_until = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=12)
		frappe.db.set_value(
			"Payment Attempt", attempt, {"status": "Initiated", "gateway_hold_until": hold_until}
		)
		self.assertFalse([a for a in alerts.stale_attempts() if a["subject"] == attempt])

		frappe.db.set_value("Payment Attempt", attempt, "gateway_hold_until", None)
		self.assertTrue([a for a in alerts.stale_attempts() if a["subject"] == attempt])

	def test_a_charge_the_gateway_refused_to_create_is_an_alert(self):
		from central.billing.payments import decline

		invoice = self._open_invoice()
		attempt = self._captured_attempt(invoice)
		frappe.db.set_value(
			"Payment Attempt",
			attempt,
			{
				"status": "Failed",
				"failure_code": decline.REQUEST_REFUSED,
				"failure_reason": "contact missing",
			},
		)

		found = [a for a in alerts.refused_charges() if a["subject"] == attempt]
		self.assertEqual(len(found), 1)
		self.assertIn("contact missing", found[0]["detail"])

	def test_a_failed_accounting_sync_is_an_alert(self):
		invoice = self._open_invoice()
		frappe.db.set_value(
			"Invoice", invoice, {"erpnext_sync_status": "Failed", "erpnext_sync_error": "no customer"}
		)

		found = [a for a in alerts.failed_accounting_syncs() if a["subject"] == invoice]
		self.assertEqual(len(found), 1)
		self.assertIn("no customer", found[0]["detail"])
