# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Team Notification feed — the console's unified in-app inbox (billing + server)."""

import frappe

from central import notification as feed
from central.billing.platform import notifications as billing_notify
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_atlas_instance, ensure_team
from central.notification import api as notif_api

TEAM = "team-feed"
OTHER = "team-feed-other"


class TeamNotificationBase(IntegrationTestCase):
	def setUp(self):
		ensure_team(TEAM)
		ensure_team(OTHER)
		self._purge()

	def tearDown(self):
		self._purge()

	def _purge(self):
		for t in (TEAM, OTHER):
			frappe.db.delete("Team Notification", {"team": t})
			frappe.db.delete("Billing Notification Log", {"team": t})
		frappe.db.commit()


class TestFeedWriter(TeamNotificationBase):
	def test_create_and_unread_count(self):
		feed.create_notification(TEAM, "Hello", category="Server", severity="Warning")
		feed.create_notification(TEAM, "World", category="Billing", severity="Info")
		self.assertEqual(feed.unread_count(TEAM), 2)

	def test_billing_notify_writes_feed_entry_with_action(self):
		# A billing event lands in the in-app feed with a mapped severity + action route.
		billing_notify.notify(
			TEAM,
			"Payment Failure",
			context={"invoice": "INV-9", "reason": "declined"},
			reference_doctype="Invoice",
			reference_name="INV-9",
		)
		rows = frappe.get_all(
			"Team Notification",
			{"team": TEAM, "event_type": "payment_failure"},
			["severity", "action_label", "action_route", "category", "message"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].severity, "Error")
		self.assertEqual(rows[0].category, "Billing")
		self.assertEqual(rows[0].action_route, "/billing/invoices")

	def test_notify_writes_feed_in_app(self):
		out = billing_notify.notify(TEAM, "Payment Failure", context={"invoice": "INV-2", "reason": "x"})
		self.assertTrue(out["sent"])
		self.assertEqual(feed.unread_count(TEAM), 1)


class TestFeedAPI(TeamNotificationBase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_list_returns_items_and_unread(self):
		feed.create_notification(TEAM, "A")
		feed.create_notification(TEAM, "B")
		out = notif_api.list_notifications(team=TEAM)
		self.assertEqual(len(out["items"]), 2)
		self.assertEqual(out["unread"], 2)

	def test_category_and_unread_filters(self):
		feed.create_notification(TEAM, "srv", category="Server")
		feed.create_notification(TEAM, "bill", category="Billing")
		self.assertEqual(len(notif_api.list_notifications(team=TEAM, category="Server")["items"]), 1)

	def test_mark_read_and_mark_all(self):
		a = feed.create_notification(TEAM, "A").name
		feed.create_notification(TEAM, "B")
		out = notif_api.mark_notification_read(name=a, team=TEAM)
		self.assertEqual(out["unread"], 1)
		self.assertTrue(
			frappe.db.exists("Notification Read", {"user": frappe.session.user, "notification": a})
		)
		out = notif_api.mark_all_notifications_read(team=TEAM)
		self.assertEqual(out["unread"], 0)
		self.assertEqual(feed.unread_count(TEAM), 0)

	def test_mark_read_rejects_other_teams_row(self):
		# A row belonging to another team can't be marked read via this team's scope.
		foreign = feed.create_notification(OTHER, "not yours").name
		with self.assertRaises(frappe.PermissionError):
			notif_api.mark_notification_read(name=foreign, team=TEAM)

	def test_read_state_independent_per_user(self):
		user_a = frappe.session.user
		user_b = "test-reader@example.com"
		if not frappe.db.exists("User", user_b):
			frappe.get_doc(
				{"doctype": "User", "email": user_b, "first_name": "Test Reader", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		a = feed.create_notification(TEAM, "Alpha").name
		feed.create_notification(TEAM, "Beta").name

		notif_api.mark_notification_read(name=a, team=TEAM)

		frappe.set_user(user_b)
		self.assertEqual(feed.unread_count(TEAM), 2, "user_b should see both as unread")
		self.assertFalse(
			frappe.db.exists("Notification Read", {"user": user_b, "notification": a}),
			"user_b must not inherit user_a's read state",
		)
		frappe.set_user(user_a)

		self.assertEqual(feed.unread_count(TEAM), 1, "user_a should see one remaining unread")


class TestServerFailureFeed(TeamNotificationBase):
	CLUSTER = "feed-region"

	def setUp(self):
		super().setUp()
		ensure_atlas_instance(self.CLUSTER)
		frappe.db.delete("Asset", {"resource_id": "vm-feed-1"})

	def test_asset_failed_emits_server_notification(self):
		# A mirror flipping to Failed drops a Server-category error into the feed.
		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"resource_id": "vm-feed-1",
				"team": TEAM,
				"cluster": self.CLUSTER,
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
		asset.status = "Failed"
		asset.save(ignore_permissions=True)
		rows = frappe.get_all(
			"Team Notification", {"team": TEAM, "event_type": "server_failed"}, ["severity", "category"]
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].severity, "Error")
		self.assertEqual(rows[0].category, "Server")
		frappe.db.delete("Asset", {"resource_id": "vm-feed-1"})
