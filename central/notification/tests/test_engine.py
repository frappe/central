# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Notification engine — the dispatch layer that wires Event Types to the feed."""

from unittest.mock import patch

import frappe
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_team, make_user


TEAM = "team-engine"


class EngineTestBase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		ensure_team(TEAM)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		frappe.db.delete("Team Notification", {"team": TEAM})
		frappe.db.delete("Notification Event Type")
		frappe.db.delete("User Notification Preference", {"team": TEAM})
		frappe.db.commit()

	def _ensure_event_type(self, event_type, *, category="Server", severity="Warning",
						   required_cap="server:view", in_app_title="Event happened",
						   in_app_body="Something broke", direct_recipients="None",
						   create_in_app=True):
		if frappe.db.exists("Notification Event Type", event_type):
			return frappe.get_doc("Notification Event Type", event_type)
		return frappe.get_doc({
			"doctype": "Notification Event Type",
			"event_type": event_type,
			"category": category,
			"severity": severity,
			"required_cap": required_cap,
			"in_app_title": in_app_title,
			"in_app_body": in_app_body,
			"direct_recipients": direct_recipients,
			"create_in_app": int(create_in_app),
		}).insert(ignore_permissions=True)


class TestDispatchCreatesFeedEntry(EngineTestBase):
	def test_dispatch_creates_team_notification_with_required_cap(self):
		"""dispatch() writes a Team Notification whose required_cap matches the Event Type registry."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="Backup failed",
				 reference_doctype="Site", reference_name="my-site")

		rows = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "backup_failure"},
			["title", "message", "category", "severity", "required_cap",
			 "reference_doctype", "reference_name"],
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

		dispatch(TEAM, "backup_failure", message="pg_dump error",
				 reference_doctype="Site", reference_name="my-site")

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

		first = dispatch(TEAM, "backup_failure", message="first",
						 reference_doctype="Site", reference_name="my-site")
		self.assertTrue(first["created"])

		second = dispatch(TEAM, "backup_failure", message="second",
						  reference_doctype="Site", reference_name="my-site")
		self.assertFalse(second["created"])
		self.assertEqual(second["reason"], "duplicate")

		count = frappe.db.count("Team Notification", {"team": TEAM, "event_type": "backup_failure"})
		self.assertEqual(count, 1)

	def test_allows_same_event_after_read(self):
		"""Once the existing notification is read, a new one can be created."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		result = dispatch(TEAM, "backup_failure", message="first",
						  reference_doctype="Site", reference_name="my-site")
		doc_name = result["notification"]
		frappe.db.set_value("Team Notification", doc_name, {"is_read": 1})

		second = dispatch(TEAM, "backup_failure", message="second",
						  reference_doctype="Site", reference_name="my-site")
		self.assertTrue(second["created"])

	def test_allows_different_reference_name(self):
		"""Different reference_name values are not considered duplicates."""
		self._ensure_event_type("backup_failure")

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="a",
				 reference_doctype="Site", reference_name="site-a")
		second = dispatch(TEAM, "backup_failure", message="b",
						  reference_doctype="Site", reference_name="site-b")
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
		self._ensure_event_type("payment_failure", category="Billing",
							   severity="Error", required_cap="billing:view",
							   in_app_title="Payment failed", in_app_body="Payment failed")

		from central.notification.engine import dispatch

		dispatch(TEAM, "payment_failure", message="Card declined",
				 reference_doctype="Invoice", reference_name="INV-1")

		recipients = sorted(call.kwargs.get("recipients", call.args[0] if call.args else [])
						   for call in mock_sendmail.call_args_list)
		self.assertIn([self.user_a], recipients)
		self.assertIn([self.user_b], recipients)

	@patch("central.notification.engine.frappe.sendmail")
	def test_skips_member_with_email_disabled(self, mock_sendmail):
		"""A member with email_enabled=False for the category does not receive an email."""
		self._ensure_event_type("payment_failure", category="Billing",
							   severity="Error", required_cap="billing:view",
							   in_app_title="Payment failed", in_app_body="Payment failed")
		frappe.get_doc({
			"doctype": "User Notification Preference",
			"user": self.user_a,
			"team": TEAM,
			"category": "Billing",
			"email_enabled": 0,
			"in_app_enabled": 1,
		}).insert(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(TEAM, "payment_failure", message="Card declined",
				 reference_doctype="Invoice", reference_name="INV-1")

		recipients = [call.kwargs.get("recipients", call.args[0] if call.args else [])
					  for call in mock_sendmail.call_args_list]
		self.assertNotIn([self.user_a], recipients)
		self.assertIn([self.user_b], recipients)

	@patch("central.notification.engine.frappe.sendmail")
	def test_skips_member_without_required_capability(self, mock_sendmail):
		"""A member who lacks the required_cap does not receive an email."""
		self._ensure_event_type("backup_failure", required_cap="server:view")
		# Create a custom role with only billing:view (no server:view).
		role = frappe.get_doc({
			"doctype": "Team Role",
			"role_name": f"Billing Only {frappe.generate_hash(4)}",
			"is_system": 0,
			"team": TEAM,
			"capabilities": [{"capability": "billing:view"}],
		}).insert(ignore_permissions=True)
		# Re-add user_b with the limited role.
		team = frappe.get_doc("Team", TEAM)
		team.members = [m for m in team.members if m.user != self.user_b]
		team.append("members", {"user": self.user_b, "role": role.name, "status": "Active"})
		team.save(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="Backup failed",
				 reference_doctype="Site", reference_name="my-site")

		all_recipients = [r for call in mock_sendmail.call_args_list
						  for r in (call.kwargs.get("recipients", call.args[0] if call.args else []))]
		# user_b (lacking server:view) must not receive an email.
		self.assertNotIn(self.user_b, all_recipients)


class TestSaveUserPreferences(EngineTestBase):
	def setUp(self):
		super().setUp()
		self.user = make_user("prefs-user@example.com")
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
		billing_only_role = frappe.get_doc({
			"doctype": "Team Role",
			"role_name": f"Billing Only {frappe.generate_hash(4)}",
			"is_system": 0,
			"team": TEAM,
			"capabilities": [{"capability": "billing:view"}],
		}).insert(ignore_permissions=True)
		team = frappe.get_doc("Team", TEAM)
		team.append("members", {"user": self.user_billing_only, "role": billing_only_role.name, "status": "Active"})
		team.append("members", {"user": self.user_viewer, "role": "Viewer", "status": "Active"})
		team.save(ignore_permissions=True)

	def test_list_filters_by_required_cap(self):
		"""A notification with required_cap=billing:view is invisible to a user lacking it."""
		self._ensure_event_type("payment_failure", category="Billing",
							   required_cap="billing:view")
		self._ensure_event_type("backup_failure", category="Server",
							   required_cap="server:view")

		from central.notification.engine import dispatch

		dispatch(TEAM, "payment_failure", message="Card declined",
				 reference_doctype="Invoice", reference_name="INV-1")
		dispatch(TEAM, "backup_failure", message="Backup failed",
				 reference_doctype="Site", reference_name="my-site")

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
		self._ensure_event_type("backup_failure", category="Server",
							   severity="Warning", required_cap="server:view",
							   in_app_title="Backup failed for {{ reference_name }}",
							   in_app_body="{{ message }}")

	def test_pilot_event_creates_notification(self):
		"""A valid pilot event dispatches through the engine and creates a notification."""
		# Simulate a resolved pilot credential.
		class FakeCredential:
			team = TEAM

		frappe.local.pilot_credential = FakeCredential()

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


class TestTemplateContext(EngineTestBase):
	def test_reference_doctype_in_template_context(self):
		"""reference_doctype is available as a Jinja template variable."""
		self._ensure_event_type(
			"backup_failure",
			in_app_title="Backup failed for {{ reference_name }} ({{ reference_doctype }})",
			in_app_body="Type: {{ reference_doctype }}, Name: {{ reference_name }}",
		)

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="pg_dump error",
				 reference_doctype="Site", reference_name="my-site")

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
		self._ensure_event_type("backup_failure", category="Server",
							   required_cap="server:view")
		# Disable in-app for user_a on Server category.
		frappe.get_doc({
			"doctype": "User Notification Preference",
			"user": self.user_a,
			"team": TEAM,
			"category": "Server",
			"email_enabled": 1,
			"in_app_enabled": 0,
		}).insert(ignore_permissions=True)

		from central.notification.engine import dispatch

		dispatch(TEAM, "backup_failure", message="Backup failed",
				 reference_doctype="Site", reference_name="my-site")

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
