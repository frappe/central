# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from central.billing.tests.utils import make_user, run_enqueued_inline
from central.notification.digest import is_digest_due, send_digest, send_due_digests
from central.notification.engine import dispatch
from central.notification.tests.test_engine import TEAM, EngineTestBase


class TestDigestDelivery(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.enterContext(patch("central.notification.engine.frappe.enqueue", side_effect=run_enqueued_inline))
		self.user = make_user("digest-user@example.com")
		frappe.db.set_value("User", self.user, "time_zone", frappe.utils.get_system_timezone())
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def _daily_preference(self, events=None):
		return frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.user,
				"team": TEAM,
				"category": "Server",
				"email_enabled": 1,
				"in_app_enabled": 1,
				"frequency": "Daily",
				"digest_hour": 7,
				"events": events or [],
			}
		).insert(ignore_permissions=True)

	def _digest_recipients(self, mock_sendmail):
		return [call.kwargs["recipients"] for call in mock_sendmail.call_args_list]

	def test_daily_event_waits_for_the_digest(self):
		self._ensure_event_type("backup_failure")
		self._daily_preference()

		with patch("central.notification.engine.frappe.sendmail") as mock_sendmail:
			dispatch(TEAM, "backup_failure", message="pg_dump exited with code 1")

		self.assertNotIn([self.user], self._digest_recipients(mock_sendmail))

	def test_critical_event_is_sent_at_once_even_when_muted(self):
		self._ensure_event_type("server_failed", is_critical=True)
		self._daily_preference(events=[{"event_type": "server_failed", "email_enabled": 0}])

		with patch("central.notification.engine.frappe.sendmail") as mock_sendmail:
			dispatch(TEAM, "server_failed", message="Server failed")

		self.assertIn([self.user], self._digest_recipients(mock_sendmail))

	def test_digest_holds_new_entries_only(self):
		self._ensure_event_type("backup_failure", in_app_title="Backup failed")
		self._ensure_event_type("site_recovered", in_app_title="Site recovered")
		self._ensure_event_type("server_failed", in_app_title="Server failed", is_critical=True)
		self._ensure_event_type("snapshot_failure", in_app_title="Snapshot failed")
		self._daily_preference(events=[{"event_type": "snapshot_failure", "email_enabled": 0}])
		since = add_to_date(now_datetime(), seconds=-1)
		for event_type in ("backup_failure", "site_recovered", "server_failed", "snapshot_failure"):
			dispatch(TEAM, event_type, message="x")

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		self.assertEqual(mock_sendmail.call_count, 1)
		body = mock_sendmail.call_args.kwargs["message"]
		self.assertIn("Backup failed", body)
		self.assertIn("Site recovered", body)
		self.assertNotIn("Server failed", body)
		self.assertNotIn("Snapshot failed", body)

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": now_datetime()}, "Daily")
		mock_sendmail.assert_not_called()

	def test_due_digest_moves_last_digest_at(self):
		self._ensure_event_type("backup_failure")
		preference = self._daily_preference()
		frappe.db.set_value(
			"User Notification Preference", preference.name, "last_digest_at", add_to_date(None, days=-1)
		)
		dispatch(TEAM, "backup_failure", message="x")
		seven_am = now_datetime().replace(hour=7, minute=5)

		with (
			patch("central.notification.digest.now_datetime", return_value=seven_am),
			patch("central.notification.digest.frappe.sendmail") as mock_sendmail,
		):
			send_due_digests()

		self.assertIn([self.user], self._digest_recipients(mock_sendmail))
		last_digest_at = frappe.db.get_value(
			"User Notification Preference", preference.name, "last_digest_at"
		)
		self.assertEqual(last_digest_at, seven_am)

	def test_leaving_the_digest_sends_what_was_waiting(self):
		preference = self._daily_preference()
		preference.frequency = "Instant"

		with patch(
			"central.notification.doctype.user_notification_preference.user_notification_preference.frappe.enqueue"
		) as mock_enqueue:
			preference.save(ignore_permissions=True)

		self.assertEqual(mock_enqueue.call_args.args[0], "central.notification.digest.send_digest")
		self.assertIsNone(preference.last_digest_at)


class TestDigestSchedule(EngineTestBase):
	def test_weekly_digest_is_due_on_monday_only(self):
		zone = frappe.utils.get_system_timezone()
		monday = frappe.utils.get_datetime("2026-10-26 07:05:00")
		preference = frappe._dict(frequency="Weekly", digest_hour=7)

		self.assertTrue(is_digest_due(preference, zone, monday))
		self.assertFalse(is_digest_due(preference, zone, add_to_date(monday, days=1)))
		self.assertFalse(is_digest_due(preference, zone, add_to_date(monday, hours=1)))
