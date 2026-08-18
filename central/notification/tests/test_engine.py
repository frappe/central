# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification engine — the dispatch layer that wires Event Types to the feed."""

from typing import ClassVar
from unittest.mock import patch

import frappe

from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team, make_user

TEAM = "team-engine"


_FIXTURE_FIELDS = [
	"category",
	"severity",
	"required_cap",
	"direct_recipients",
	"email_template",
	"in_app_title",
	"in_app_body",
	"action_label",
	"action_route",
	"create_in_app",
]


class EngineTestBase(IntegrationTestCase):
	_created_event_types: ClassVar[set[str]] = set()
	_displaced_fixtures: ClassVar[list[dict]] = []

	def setUp(self):
		frappe.set_user("Administrator")
		ensure_team(TEAM)
		self.__class__._created_event_types = set()
		self.__class__._displaced_fixtures = []
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Team Notification", {"team": TEAM})
		created = self.__class__._created_event_types
		if created:
			frappe.db.delete("Notification Event Type", {"name": ["in", list(created)]})
		displaced = self.__class__._displaced_fixtures
		if displaced:
			for record in displaced:
				if not frappe.db.exists("Notification Event Type", record["event_type"]):
					frappe.get_doc({"doctype": "Notification Event Type", **record}).insert(
						ignore_permissions=True
					)
			self.__class__._displaced_fixtures = []
		frappe.db.delete("User Notification Preference", {"team": TEAM})
		frappe.db.commit()

	def _ensure_event_type(
		self,
		event_type,
		*,
		category="Server",
		severity="Warning",
		required_cap="server:view",
		in_app_title="Event happened",
		in_app_body="Something broke",
		direct_recipients="None",
		create_in_app=True,
	):
		if frappe.db.exists("Notification Event Type", event_type):
			original = frappe.db.get_value(
				"Notification Event Type", event_type, _FIXTURE_FIELDS, as_dict=True
			)
			if original:
				self.__class__._displaced_fixtures.append(
					{"event_type": event_type, **{k: original[k] for k in _FIXTURE_FIELDS}}
				)
			frappe.db.delete("Notification Event Type", {"name": event_type})
			frappe.db.commit()
		doc = frappe.get_doc(
			{
				"doctype": "Notification Event Type",
				"event_type": event_type,
				"category": category,
				"severity": severity,
				"required_cap": required_cap,
				"in_app_title": in_app_title,
				"in_app_body": in_app_body,
				"direct_recipients": direct_recipients,
				"create_in_app": int(create_in_app),
			}
		).insert(ignore_permissions=True)
		self.__class__._created_event_types.add(event_type)
		return doc


class TestDispatchCreatesFeedEntry(EngineTestBase):
	def test_dispatch_creates_team_notification_with_required_cap(self):
		"""dispatch() writes a Team Notification whose required_cap matches the Event Type registry."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"backup_failure",
			message="Backup failed",
			reference_doctype="Site",
			reference_name="my-site",
		)

		rows = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "backup_failure"},
			[
				"title",
				"message",
				"category",
				"severity",
				"required_cap",
				"reference_doctype",
				"reference_name",
			],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.required_cap, "server:view")
		self.assertEqual(row.category, "Server")
		self.assertEqual(row.severity, "Warning")
		self.assertEqual(row.reference_doctype, "Site")
		self.assertEqual(row.reference_name, "my-site")

	def test_dispatch_renders_jinja_title_and_body(self):
		"""The in-app title and body are rendered from the Event Type's Jinja templates."""
		self._ensure_event_type(
			"backup_failure",
			in_app_title="Backup failed for {{ reference_name }}",
			in_app_body="Backup on {{ team }} failed: {{ message }}",
		)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"backup_failure",
			message="pg_dump error",
			reference_doctype="Site",
			reference_name="my-site",
		)

		row = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "backup_failure"},
			["title", "message"],
		)[0]
		self.assertEqual(row.title, "Backup failed for my-site")
		self.assertIn("pg_dump error", row.message)


class TestDeduplication(EngineTestBase):
	def test_suppresses_duplicate_unread_notification(self):
		"""An unread notification with the same event_type + reference_name blocks a second."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		first = dispatch(
			TEAM, "backup_failure", message="first", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(first["created"])

		second = dispatch(
			TEAM, "backup_failure", message="second", reference_doctype="Site", reference_name="my-site"
		)
		self.assertFalse(second["created"])
		self.assertEqual(second["reason"], "duplicate")

		count = frappe.db.count("Team Notification", {"team": TEAM, "event_type": "backup_failure"})
		self.assertEqual(count, 1)

	def test_allows_same_event_after_window_expires(self):
		"""Once the dedup window expires, a new notification can be created."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import DEDUP_WINDOW_MINUTES, dispatch

		result = dispatch(
			TEAM, "backup_failure", message="first", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(result["created"])

		# Second dispatch within the window is suppressed.
		suppressed = dispatch(
			TEAM, "backup_failure", message="second", reference_doctype="Site", reference_name="my-site"
		)
		self.assertFalse(suppressed["created"])
		self.assertEqual(suppressed["reason"], "duplicate")

		# Simulate window expiry by moving the first notification's creation
		# timestamp outside the window.
		cutoff = frappe.utils.add_to_date(None, minutes=-(DEDUP_WINDOW_MINUTES + 1))
		frappe.db.set_value("Team Notification", result["notification"], "creation", cutoff)
		frappe.db.commit()

		third = dispatch(
			TEAM, "backup_failure", message="third", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(third["created"])

	def test_allows_different_reference_name(self):
		"""Different reference_name values are not considered duplicates."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="a", reference_doctype="Site", reference_name="site-a")
		second = dispatch(
			TEAM, "backup_failure", message="b", reference_doctype="Site", reference_name="site-b"
		)
		self.assertTrue(second["created"])
		self.assertEqual(frappe.db.count("Team Notification", {"team": TEAM}), 2)

	def test_allows_same_event_without_reference_name(self):
		"""Events without a reference_name are never deduplicated."""
		self._ensure_event_type("team_suspension")

		from central.notification.engine import dispatch

		dispatch(TEAM, "team_suspension", message="first")
		second = dispatch(TEAM, "team_suspension", message="second")
		self.assertTrue(second["created"])
		self.assertEqual(frappe.db.count("Team Notification", {"team": TEAM}), 2)

	def test_allows_new_incident_after_state_change(self):
		"""A different event type for the same ref signals state change — not a duplicate."""
		self._ensure_event_type("backup_failure")
		self._ensure_event_type("site_recovered")

		from central.notification.engine import dispatch

		first = dispatch(
			TEAM, "backup_failure", message="down", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(first["created"])

		# State changes: recovery event for the same reference.
		recovery = dispatch(
			TEAM, "site_recovered", message="back up", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(recovery["created"])

		# Same failure again — state changed since first occurrence → allowed.
		second = dispatch(
			TEAM, "backup_failure", message="down again", reference_doctype="Site", reference_name="my-site"
		)
		self.assertTrue(second["created"])

	def test_suppresses_when_state_unchanged(self):
		"""Same event repeated without state change is still deduped."""
		self._ensure_event_type("backup_failure")
		self._ensure_event_type("site_recovered")

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="first", reference_doctype="Site", reference_name="my-site")

		# Different reference — unrelated, not a state change for my-site.
		dispatch(
			TEAM, "site_recovered", message="other", reference_doctype="Site", reference_name="other-site"
		)

		# Same failure, same ref, no state change for my-site → suppressed.
		dup = dispatch(
			TEAM, "backup_failure", message="second", reference_doctype="Site", reference_name="my-site"
		)
		self.assertFalse(dup["created"])
		self.assertEqual(dup["reason"], "duplicate")


class TestEmailFanout(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.user_a = make_user("fanout-a@example.com")
		self.user_b = make_user("fanout-b@example.com")
		self._add_members([self.user_a, self.user_b])

	def _add_members(self, users):
		"""Add users as active members of the test team (non-owner roles)."""
		team = frappe.get_doc("Team", TEAM)
		for u in users:
			team.append("members", {"user": u, "role": "Billing", "status": "Active"})
		team.save(ignore_permissions=True)

	@patch("central.notification.engine.frappe.sendmail")
	def test_emails_qualified_members(self, mock_sendmail):
		"""All active members with the required capability receive an email."""
		self._ensure_event_type(
			"payment_failure",
			category="Billing",
			severity="Error",
			required_cap="billing:view",
			in_app_title="Payment failed",
			in_app_body="Payment failed",
		)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"payment_failure",
			message="Card declined",
			reference_doctype="Invoice",
			reference_name="INV-1",
		)

		recipients = sorted(
			call.kwargs.get("recipients", call.args[0] if call.args else [])
			for call in mock_sendmail.call_args_list
		)
		self.assertIn([self.user_a], recipients)
		self.assertIn([self.user_b], recipients)

	@patch("central.notification.engine.frappe.sendmail")
	def test_skips_member_with_email_disabled(self, mock_sendmail):
		"""A member with email_enabled=False for the category does not receive an email."""
		self._ensure_event_type(
			"payment_failure",
			category="Billing",
			severity="Error",
			required_cap="billing:view",
			in_app_title="Payment failed",
			in_app_body="Payment failed",
		)
		frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.user_a,
				"team": TEAM,
				"category": "Billing",
				"email_enabled": 0,
				"in_app_enabled": 1,
			}
		).insert(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"payment_failure",
			message="Card declined",
			reference_doctype="Invoice",
			reference_name="INV-1",
		)

		recipients = [
			call.kwargs.get("recipients", call.args[0] if call.args else [])
			for call in mock_sendmail.call_args_list
		]
		self.assertNotIn([self.user_a], recipients)
		self.assertIn([self.user_b], recipients)

	@patch("central.notification.engine.frappe.sendmail")
	def test_skips_member_without_required_capability(self, mock_sendmail):
		"""A member who lacks the required_cap does not receive an email."""
		self._ensure_event_type("backup_failure", required_cap="server:view")
		# Create a custom role with only billing:view (no server:view).
		role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"role_name": f"Billing Only {frappe.generate_hash(4)}",
				"is_system": 0,
				"team": TEAM,
				"capabilities": [{"capability": "billing:view"}],
			}
		).insert(ignore_permissions=True)
		# Re-add user_b with the limited role.
		team = frappe.get_doc("Team", TEAM)
		team.members = [m for m in team.members if m.user != self.user_b]
		team.append("members", {"user": self.user_b, "role": role.name, "status": "Active"})
		team.save(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"backup_failure",
			message="Backup failed",
			reference_doctype="Site",
			reference_name="my-site",
		)

		all_recipients = [
			r
			for call in mock_sendmail.call_args_list
			for r in (call.kwargs.get("recipients", call.args[0] if call.args else []))
		]
		# user_b (lacking server:view) must not receive an email.
		self.assertNotIn(self.user_b, all_recipients)


class TestSaveUserPreferences(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.user = make_user("prefs-user@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)
		frappe.set_user(self.user)

	def test_creates_preferences_for_user(self):
		"""save_user_preferences creates UserNotificationPreference records."""
		from central.notification.api import save_user_preferences

		save_user_preferences(
			team=TEAM,
			preferences=[
				{"category": "Billing", "email_enabled": 1, "in_app_enabled": 0},
				{"category": "Server", "email_enabled": 0, "in_app_enabled": 1},
			],
		)

		billing = frappe.db.get_value(
			"User Notification Preference",
			{"user": self.user, "team": TEAM, "category": "Billing"},
			["email_enabled", "in_app_enabled"],
			as_dict=True,
		)
		server = frappe.db.get_value(
			"User Notification Preference",
			{"user": self.user, "team": TEAM, "category": "Server"},
			["email_enabled", "in_app_enabled"],
			as_dict=True,
		)
		self.assertTrue(billing.email_enabled)
		self.assertFalse(billing.in_app_enabled)
		self.assertFalse(server.email_enabled)
		self.assertTrue(server.in_app_enabled)

	def test_updates_existing_preferences(self):
		"""Re-saving upserts the existing preference row."""
		from central.notification.api import save_user_preferences

		save_user_preferences(
			team=TEAM,
			preferences=[{"category": "Billing", "email_enabled": 1, "in_app_enabled": 1}],
		)
		save_user_preferences(
			team=TEAM,
			preferences=[{"category": "Billing", "email_enabled": 0, "in_app_enabled": 1}],
		)

		pref = frappe.db.get_value(
			"User Notification Preference",
			{"user": self.user, "team": TEAM, "category": "Billing"},
			["email_enabled", "in_app_enabled"],
			as_dict=True,
		)
		self.assertFalse(pref.email_enabled)
		self.assertTrue(pref.in_app_enabled)
		# Must be exactly one row, not two.
		count = frappe.db.count(
			"User Notification Preference",
			{"user": self.user, "team": TEAM, "category": "Billing"},
		)
		self.assertEqual(count, 1)

	def test_returns_saved_preferences(self):
		"""The endpoint returns the saved preferences for confirmation."""
		from central.notification.api import save_user_preferences

		out = save_user_preferences(
			team=TEAM,
			preferences=[{"category": "Billing", "email_enabled": 1, "in_app_enabled": 0}],
		)
		self.assertTrue(out["saved"])
		self.assertEqual(len(out["preferences"]), 1)
		self.assertEqual(out["preferences"][0]["category"], "Billing")


class TestCapabilityFilteredList(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.user_billing_only = make_user("list-billing-only@example.com")
		self.user_viewer = make_user("list-viewer@example.com")
		# Custom role with only billing:view (no server:view) for the billing user.
		billing_only_role = frappe.get_doc(
			{
				"doctype": "Team Role",
				"role_name": f"Billing Only {frappe.generate_hash(4)}",
				"is_system": 0,
				"team": TEAM,
				"capabilities": [{"capability": "billing:view"}],
			}
		).insert(ignore_permissions=True)
		team = frappe.get_doc("Team", TEAM)
		team.append(
			"members", {"user": self.user_billing_only, "role": billing_only_role.name, "status": "Active"}
		)
		team.append("members", {"user": self.user_viewer, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def test_list_filters_by_required_cap(self):
		"""A notification with required_cap=billing:view is invisible to a user lacking it."""
		self._ensure_event_type("payment_failure", category="Billing", required_cap="billing:view")
		self._ensure_event_type("backup_failure", category="Server", required_cap="server:view")

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"payment_failure",
			message="Card declined",
			reference_doctype="Invoice",
			reference_name="INV-1",
		)
		dispatch(
			TEAM,
			"backup_failure",
			message="Backup failed",
			reference_doctype="Site",
			reference_name="my-site",
		)

		from central import notification as feed

		# Viewer has server:view but not billing:view — should see only backup_failure.
		out = feed.list_notifications(TEAM, user=self.user_viewer)
		event_types = [i.event_type for i in out["items"]]
		self.assertIn("backup_failure", event_types)
		self.assertNotIn("payment_failure", event_types)

		# Billing-only has billing:view but not server:view — should see only payment_failure.
		out = feed.list_notifications(TEAM, user=self.user_billing_only)
		event_types = [i.event_type for i in out["items"]]
		self.assertIn("payment_failure", event_types)
		self.assertNotIn("backup_failure", event_types)


class TestReportPilotEvent(EngineTestBase):
	def setUp(self):
		super().setUp()
		self._ensure_event_type(
			"backup_failure",
			category="Server",
			severity="Warning",
			required_cap="server:view",
			in_app_title="Backup failed for {{ reference_name }}",
			in_app_body="{{ message }}",
		)

	def test_pilot_event_creates_notification(self):
		"""A valid pilot event dispatches through the engine and creates a notification."""

		class FakeCredential:
			team = TEAM

		fake = FakeCredential()

		with (
			patch("central.api.pilot.PilotCredential.verify", return_value=fake),
			patch("frappe.get_request_header", return_value="fake-token"),
		):
			from central.notification.api import report_pilot_event

			out = report_pilot_event(
				event_type="backup_failure",
				message="pg_dump exited with code 1",
				reference_doctype="Site",
				reference_name="my-site",
				context={"error_code": "DISK_FULL"},
			)
		self.assertTrue(out["created"])

		rows = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "backup_failure"},
			["title", "message", "reference_name", "required_cap"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].reference_name, "my-site")
		self.assertEqual(rows[0].required_cap, "server:view")

	def test_pilot_event_refuses_non_server_category(self):
		"""A pilot may only raise Server-domain events; a Billing event type is refused
		so a bench can't fan out billing emails to the team."""
		self._ensure_event_type(
			"payment_failure",
			category="Billing",
			severity="Error",
			required_cap="billing:view",
			in_app_title="Payment failed",
			in_app_body="{{ message }}",
		)

		class FakeCredential:
			team = TEAM

		with (
			patch("central.api.pilot.PilotCredential.verify", return_value=FakeCredential()),
			patch("frappe.get_request_header", return_value="fake-token"),
		):
			from central.notification.api import report_pilot_event

			with self.assertRaises(frappe.PermissionError):
				report_pilot_event(event_type="payment_failure", message="x")


class TestTemplateContext(EngineTestBase):
	def test_reference_doctype_in_template_context(self):
		"""reference_doctype is available as a Jinja template variable."""
		self._ensure_event_type(
			"backup_failure",
			in_app_title="Backup failed for {{ reference_name }} ({{ reference_doctype }})",
			in_app_body="Type: {{ reference_doctype }}, Name: {{ reference_name }}",
		)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"backup_failure",
			message="pg_dump error",
			reference_doctype="Site",
			reference_name="my-site",
		)

		row = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "backup_failure"},
			["title", "message"],
		)[0]
		self.assertIn("Site", row.title)
		self.assertIn("Site", row.message)
		self.assertIn("my-site", row.message)


class TestInAppEnabledFilter(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.user_a = make_user("inapp-a@example.com")
		self.user_b = make_user("inapp-b@example.com")
		# Both users get Viewer role (has server:view and billing:view).
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user_a, "role": "Viewer", "status": "Active"})
		team.append("members", {"user": self.user_b, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def test_user_with_in_app_disabled_does_not_see_notification(self):
		"""A user with in_app_enabled=0 for a category does not see those notifications."""
		self._ensure_event_type("backup_failure", category="Server", required_cap="server:view")
		# Disable in-app for user_a on Server category.
		frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": self.user_a,
				"team": TEAM,
				"category": "Server",
				"email_enabled": 1,
				"in_app_enabled": 0,
			}
		).insert(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"backup_failure",
			message="Backup failed",
			reference_doctype="Site",
			reference_name="my-site",
		)

		from central import notification as feed

		# user_a should NOT see the notification.
		out = feed.list_notifications(TEAM, user=self.user_a)
		event_types = [i.event_type for i in out["items"]]
		self.assertNotIn("backup_failure", event_types)

		# user_b (no preference = default enabled) SHOULD see it.
		out = feed.list_notifications(TEAM, user=self.user_b)
		event_types = [i.event_type for i in out["items"]]
		self.assertIn("backup_failure", event_types)


class TestMemberInvitedSuppression(EngineTestBase):
	def test_member_invited_does_not_create_team_notification(self):
		"""member_invited event sends email but does NOT create a Team Notification."""
		self._ensure_event_type(
			"member_invited",
			category="Team",
			severity="Info",
			required_cap="team:manage_members",
			in_app_title="Team invitation",
			in_app_body="You have been invited to join {{ team }}.",
			direct_recipients="None",
			create_in_app=False,
		)

		from central.notification.engine import dispatch

		result = dispatch(TEAM, "member_invited", message="new-member@example.com")
		self.assertFalse(result["created"])
		self.assertIsNone(result["notification"])

		count = frappe.db.count("Team Notification", {"team": TEAM, "event_type": "member_invited"})
		self.assertEqual(count, 0)


class TestDirectRecipientsAffectedUser(EngineTestBase):
	@patch("central.notification.engine.frappe.sendmail")
	def test_affected_user_receives_email(self, mock_sendmail):
		"""Only the affected_user gets the email when direct_recipients='Affected User'."""
		self.user_a = make_user("direct-a@example.com")
		self.user_b = make_user("direct-b@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user_a, "role": "Viewer", "status": "Active"})
		team.append("members", {"user": self.user_b, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

		self._ensure_event_type("server_down", required_cap="server:view", direct_recipients="Affected User")

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"server_down",
			message="Server is down",
			reference_doctype="Server",
			reference_name="srv-1",
			affected_user=self.user_a,
		)

		all_recipients = [
			r
			for call in mock_sendmail.call_args_list
			for r in (call.kwargs.get("recipients", call.args[0] if call.args else []))
		]
		self.assertIn(self.user_a, all_recipients)
		self.assertNotIn(self.user_b, all_recipients)

	@patch("central.notification.engine.frappe.sendmail")
	def test_no_email_when_affected_user_not_set(self, mock_sendmail):
		"""When direct_recipients='Affected User' but affected_user is None,
		no email is sent — the mode requires an explicit target."""
		self.user_a = make_user("direct-c@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user_a, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

		self._ensure_event_type("server_down2", required_cap="server:view", direct_recipients="Affected User")

		from central.notification.engine import dispatch

		dispatch(
			TEAM, "server_down2", message="Server is down", reference_doctype="Server", reference_name="srv-2"
		)

		self.assertEqual(mock_sendmail.call_count, 0)

	@patch("central.notification.engine.frappe.sendmail")
	def test_affected_user_bypasses_capability(self, mock_sendmail):
		"""The affected_user receives the email even without the required capability."""
		self.user_a = make_user("direct-d@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user_a, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

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
		team.members = [m for m in team.members if m.user != self.user_a]
		team.append("members", {"user": self.user_a, "role": role.name, "status": "Active"})
		team.save(ignore_permissions=True)

		self._ensure_event_type("server_down3", required_cap="server:view", direct_recipients="Affected User")

		from central.notification.engine import dispatch

		dispatch(
			TEAM,
			"server_down3",
			message="Server is down",
			reference_doctype="Server",
			reference_name="srv-3",
			affected_user=self.user_a,
		)

		all_recipients = [
			r
			for call in mock_sendmail.call_args_list
			for r in (call.kwargs.get("recipients", call.args[0] if call.args else []))
		]
		self.assertIn(self.user_a, all_recipients)


class TestFeedPagination(EngineTestBase):
	"""`start` + `has_next_page` — what the console's 'Load More' pages on."""

	def setUp(self):
		super().setUp()
		self.user = make_user("paging@example.com")
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def _seed(self, count):
		from central.notification import create_notification

		for index in range(count):
			create_notification(TEAM, f"Notification {index}", category="Server", publish=False)

	def test_pages_do_not_overlap_and_report_next_page(self):
		self._seed(5)
		from central import notification as feed

		first = feed.list_notifications(TEAM, user=self.user, limit=2)
		self.assertEqual(len(first["items"]), 2)
		self.assertTrue(first["has_next_page"])

		second = feed.list_notifications(TEAM, user=self.user, start=2, limit=2)
		self.assertEqual(len(second["items"]), 2)
		self.assertTrue(second["has_next_page"])

		last = feed.list_notifications(TEAM, user=self.user, start=4, limit=2)
		self.assertEqual(len(last["items"]), 1)
		self.assertFalse(last["has_next_page"])

		names = [item.name for page in (first, second, last) for item in page["items"]]
		self.assertEqual(len(names), len(set(names)), "pages overlapped")

	def test_exact_page_boundary_has_no_next_page(self):
		"""A last page filled exactly to `limit` must not advertise another page."""
		self._seed(4)
		from central import notification as feed

		page = feed.list_notifications(TEAM, user=self.user, start=2, limit=2)
		self.assertEqual(len(page["items"]), 2)
		self.assertFalse(page["has_next_page"])

	def test_defaults_are_unchanged(self):
		"""Callers that never pass `start` keep the pre-pagination behaviour."""
		self._seed(3)
		from central import notification as feed

		page = feed.list_notifications(TEAM, user=self.user)
		self.assertEqual(len(page["items"]), 3)
		self.assertFalse(page["has_next_page"])
