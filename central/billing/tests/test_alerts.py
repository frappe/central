# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Operator alerts fire on what the sweeps cannot fix, and stay quiet otherwise."""

from unittest.mock import patch

import frappe

from central.billing.platform import alerts
from central.billing.tests.test_stripe_adapter import make_stripe_gateway
from central.billing.tests.utils import BillingTestCase


class TestOperatorAlerts(BillingTestCase):
	def setUp(self):
		frappe.cache().delete_value(alerts._CACHE_KEY)
		self.mail = patch.object(alerts.frappe, "sendmail").start()
		self.addCleanup(patch.stopall)
		self.gateway = make_stripe_gateway("GW-Alerts-Stripe").name

	def _quiet_sources(self, *live):
		"""Run the alert job with only the named sources live."""
		return patch.object(alerts, "SOURCES", live)

	def test_a_clean_system_pages_nobody(self):
		with self._quiet_sources(lambda: []):
			result = alerts.run_operator_alerts()
		self.assertEqual(result, {"alerts": 0, "notified": False})
		self.mail.assert_not_called()

	def test_an_open_alert_mails_the_operators(self):
		alert = {"alert": "invariant", "subject": "INV-1", "team": "t1", "detail": "C2: drift"}
		with self._quiet_sources(lambda: [alert]):
			result = alerts.run_operator_alerts()

		self.assertEqual(result["alerts"], 1)
		self.assertTrue(result["notified"])
		self.assertIn("1 invariant", self.mail.call_args.kwargs["subject"])

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

	def test_one_broken_source_does_not_blind_the_others(self):
		def broken():
			raise RuntimeError("source down")

		alert = {"alert": "failed_webhook", "subject": "WH-1", "team": None, "detail": "boom"}
		with self._quiet_sources(broken, lambda: [alert]):
			self.assertEqual(alerts.collect(), [alert])

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
