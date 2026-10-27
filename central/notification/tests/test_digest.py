# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, now_datetime

from central.billing.tests.utils import ensure_team, make_user, run_enqueued_inline
from central.notification import create_notification
from central.notification.digest import get_digest_rows, is_digest_due, send_digest, send_due_digests
from central.notification.doctype.notification_digest_setting.notification_digest_setting import (
	NotificationDigestSetting,
)
from central.notification.engine import _is_emailed_instantly, dispatch
from central.notification.tests.test_engine import TEAM, EngineTestBase


class TestDigestDelivery(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.enterContext(
			patch("central.notification.engine.frappe.enqueue", side_effect=run_enqueued_inline)
		)
		self.user = make_user("digest-user@example.com")
		frappe.db.set_value("User", self.user, "time_zone", frappe.utils.get_system_timezone())
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def _daily_preference(self, events=None, user=None):
		user = user or self.user
		preference = frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": user,
				"team": TEAM,
				"category": "Server",
				"email_enabled": 1,
				"in_app_enabled": 1,
				"frequency": "Daily",
				"events": events or [],
			}
		).insert(ignore_permissions=True)
		NotificationDigestSetting.upsert(user, TEAM, 7)
		return preference

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

	def _make_digest_due(self, user):
		frappe.db.set_value(
			"User Notification Preference",
			{"user": user, "team": TEAM},
			"last_digest_at",
			add_to_date(now_datetime(), days=-2),
		)

	def _cursor(self, user):
		return frappe.db.get_value(
			"User Notification Preference", {"user": user, "team": TEAM}, "last_digest_at"
		)

	def test_failed_send_keeps_the_cursor_for_the_next_run(self):
		self._daily_preference()
		self._make_digest_due(self.user)
		before = self._cursor(self.user)

		with patch("central.notification.digest.send_digest", side_effect=RuntimeError("smtp down")):
			send_due_digests()

		self.assertEqual(self._cursor(self.user), before)

	def test_one_failing_member_does_not_stop_the_others(self):
		other = make_user("digest-other@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": other, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)
		for user in (self.user, other):
			self._daily_preference(user=user)
			self._make_digest_due(user)
		before = {user: self._cursor(user) for user in (self.user, other)}

		def fail_for_first(user, *args, **kwargs):
			if user == self.user:
				raise RuntimeError("smtp down")

		with patch("central.notification.digest.send_digest", side_effect=fail_for_first):
			send_due_digests()

		self.assertEqual(self._cursor(self.user), before[self.user])
		self.assertGreater(self._cursor(other), before[other])

	def test_digest_rows_stop_at_the_upper_bound(self):
		self._ensure_event_type("backup_failure", in_app_title="Backup failed")
		self._daily_preference()
		for reference in ("early", "late"):
			dispatch(TEAM, "backup_failure", message=reference, reference_name=reference)
		now = now_datetime()
		for reference, minutes in (("early", -10), ("late", -1)):
			frappe.db.set_value(
				"Team Notification",
				{"team": TEAM, "reference_name": reference},
				"creation",
				add_to_date(now, minutes=minutes),
				update_modified=False,
			)

		rows, _is_capped = get_digest_rows(
			self.user, TEAM, {"Server": add_to_date(now, hours=-1)}, until=add_to_date(now, minutes=-5)
		)

		self.assertEqual(len(rows), 1)

	def test_impersonation_and_suspension_notices_are_critical(self):
		for event_type in ("team_impersonated", "team_suspended"):
			self.assertTrue(frappe.db.get_value("Notification Event Type", event_type, "is_critical"))

	def test_critical_event_is_sent_at_once_when_category_email_is_off(self):
		self._ensure_event_type("server_failed", is_critical=True)
		preference = self._daily_preference()
		frappe.db.set_value("User Notification Preference", preference.name, "email_enabled", 0)

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

	def test_digest_includes_entries_without_event_type(self):
		self._daily_preference()
		since = add_to_date(now_datetime(), seconds=-1)
		for number in range(51):
			create_notification(TEAM, f"Generic notice {number}", category="Server", publish=False)

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		body = mock_sendmail.call_args.kwargs["message"]
		self.assertIn("Generic notice", body)
		self.assertIn("1 more update is in your notification feed.", body)

	def test_one_digest_hour_per_user_and_team(self):
		self._daily_preference()
		frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.user,
				"team": TEAM,
				"category": "Billing",
				"frequency": "Daily",
			}
		).insert(ignore_permissions=True)

		NotificationDigestSetting.upsert(self.user, TEAM, 17)

		self.assertEqual(NotificationDigestSetting.get_hour(self.user, TEAM), 17)
		self.assertEqual(frappe.db.count("Notification Digest Setting", {"user": self.user, "team": TEAM}), 1)

	def test_digest_skips_events_the_member_lacks_the_capability_for(self):
		self._ensure_event_type("backup_failure", required_cap="server:view")
		self._daily_preference()
		role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"role_name": f"Billing Only {frappe.generate_hash(4)}",
				"is_system": 0,
				"team": TEAM,
				"capabilities": [{"capability": "billing:view"}],
			}
		).insert(ignore_permissions=True)
		team = frappe.get_doc("Team", TEAM)
		team.members = [member for member in team.members if member.user != self.user]
		team.append("members", {"user": self.user, "role": role.name, "status": "Active"})
		team.save(ignore_permissions=True)
		since = add_to_date(now_datetime(), seconds=-1)
		dispatch(TEAM, "backup_failure", message="x")

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		mock_sendmail.assert_not_called()

	def test_digest_skips_another_teams_events(self):
		other_team = "team-engine-other"
		ensure_team(other_team)
		self.addCleanup(frappe.db.delete, "Team Notification", {"team": other_team})
		self._ensure_event_type("backup_failure")
		self._daily_preference()
		since = add_to_date(now_datetime(), seconds=-1)
		with patch("central.notification.engine.frappe.sendmail"):
			dispatch(other_team, "backup_failure", message="x")

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		mock_sendmail.assert_not_called()

	def test_instant_and_muted_events_do_not_use_up_the_scan_limit(self):
		self._ensure_event_type("backup_failure", in_app_title="Backup failed")
		self._ensure_event_type("server_failed", is_critical=True)
		self._ensure_event_type("snapshot_failure")
		self._daily_preference(events=[{"event_type": "snapshot_failure", "email_enabled": 0}])
		since = add_to_date(now_datetime(), seconds=-1)
		with patch("central.notification.engine.frappe.sendmail"):
			dispatch(TEAM, "backup_failure", message="x")
			for number in range(3):
				dispatch(TEAM, "server_failed", message="x", reference_name=f"srv-{number}")
				dispatch(TEAM, "snapshot_failure", message="x", reference_name=f"snap-{number}")

		with (
			patch("central.notification.digest.MAX_SCAN", 3),
			patch("central.notification.digest.frappe.sendmail") as mock_sendmail,
		):
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		self.assertIn("Backup failed", mock_sendmail.call_args.kwargs["message"])

	def test_digest_says_when_the_scan_limit_cut_entries(self):
		self._ensure_event_type("backup_failure", in_app_title="Backup failed")
		self._daily_preference()
		since = add_to_date(now_datetime(), seconds=-1)
		for number in range(3):
			dispatch(TEAM, "backup_failure", message="x", reference_name=f"backup-{number}")

		for limit, ending in ((2, "2+ updates"), (3, "3 updates")):
			with (
				patch("central.notification.digest.MAX_SCAN", limit),
				patch("central.notification.digest.frappe.sendmail") as mock_sendmail,
			):
				send_digest(self.user, TEAM, {"Server": since}, "Daily")

			self.assertTrue(mock_sendmail.call_args.kwargs["subject"].endswith(ending), ending)

	def test_due_digest_moves_last_digest_at(self):
		self._ensure_event_type("backup_failure")
		preference = self._daily_preference()
		frappe.db.set_value(
			"User Notification Preference", preference.name, "last_digest_at", add_to_date(None, days=-2)
		)
		dispatch(TEAM, "backup_failure", message="x")
		started = now_datetime()

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_due_digests()

		self.assertIn([self.user], self._digest_recipients(mock_sendmail))
		last_digest_at = frappe.db.get_value(
			"User Notification Preference", preference.name, "last_digest_at"
		)
		self.assertGreaterEqual(last_digest_at, started)

	def test_digest_window_uses_the_user_time_zone(self):
		self._ensure_event_type("backup_failure")
		self._daily_preference()
		frappe.db.set_value("User", self.user, "time_zone", "Asia/Tokyo")
		dispatch(TEAM, "backup_failure", message="x")
		since = add_to_date(now_datetime(), seconds=-1)

		with patch("central.notification.digest.frappe.sendmail") as mock_sendmail:
			send_digest(self.user, TEAM, {"Server": since}, "Daily")

		body = mock_sendmail.call_args.kwargs["message"]
		local_since = (
			since.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone()))
			.astimezone(ZoneInfo("Asia/Tokyo"))
			.replace(tzinfo=None)
		)
		self.assertIn(frappe.utils.format_datetime(local_since, "medium"), body)

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
	def test_affected_user_event_is_never_held_for_the_digest(self):
		preference = {"email_enabled": True, "frequency": "Daily", "events": {}}
		event = frappe._dict(
			name="role_changed", is_critical=0, create_in_app=1, direct_recipients="Affected User"
		)

		self.assertTrue(_is_emailed_instantly(preference, event))

	def test_weekly_digest_is_due_from_its_hour_and_catches_up(self):
		zone = frappe.utils.get_system_timezone()
		last_monday = frappe.utils.get_datetime("2026-10-19 07:05:00")
		monday = frappe.utils.get_datetime("2026-10-26 07:05:00")
		preference = frappe._dict(frequency="Weekly", last_digest_at=last_monday)

		self.assertFalse(is_digest_due(preference, zone, 7, add_to_date(monday, minutes=-10)))
		self.assertTrue(is_digest_due(preference, zone, 7, monday))
		self.assertTrue(is_digest_due(preference, zone, 7, add_to_date(monday, days=2)))

		preference.last_digest_at = monday
		self.assertFalse(is_digest_due(preference, zone, 7, add_to_date(monday, days=2)))

	def test_daily_digest_catches_up_a_missed_hour(self):
		zone = frappe.utils.get_system_timezone()
		yesterday = frappe.utils.get_datetime("2026-10-26 07:05:00")
		today = frappe.utils.get_datetime("2026-10-27 07:05:00")
		preference = frappe._dict(frequency="Daily", last_digest_at=yesterday)

		self.assertFalse(is_digest_due(preference, zone, 7, add_to_date(today, minutes=-10)))
		self.assertTrue(is_digest_due(preference, zone, 7, today))
		self.assertTrue(is_digest_due(preference, zone, 7, add_to_date(today, hours=5)))
