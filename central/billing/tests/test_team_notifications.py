# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Team Notification feed — the console's unified in-app inbox (billing + server)."""

import frappe

from central import notifications as feed
from central.billing.api.dashboard import account
from central.billing.platform import notifications as billing_notify
from central.billing.tests.utils import BillingTestCase as IntegrationTestCase
from central.billing.tests.utils import ensure_atlas_instance, ensure_team

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
			{"team": TEAM, "event_type": "Payment Failure"},
			["severity", "action_label", "action_route", "category", "message"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].severity, "Error")
		self.assertEqual(rows[0].category, "Billing")
		self.assertEqual(rows[0].action_route, "/billing/invoices")

	def test_suppressed_email_still_feeds_in_app(self):
		# Opting out of the *email* must not hide the event from the dashboard feed.
		frappe.get_doc(
			{"doctype": "Notification Preference", "team": TEAM, "notify_payment_failure": 0}
		).insert(ignore_permissions=True)
		out = billing_notify.notify(TEAM, "Payment Failure", context={"invoice": "INV-2", "reason": "x"})
		self.assertFalse(out["sent"])  # email suppressed
		self.assertEqual(feed.unread_count(TEAM), 1)  # but the feed still recorded it
		frappe.db.delete("Notification Preference", {"team": TEAM})


class TestFeedAPI(TeamNotificationBase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_list_returns_items_and_unread(self):
		feed.create_notification(TEAM, "A")
		feed.create_notification(TEAM, "B")
		out = account.list_notifications(team=TEAM)
		self.assertEqual(len(out["items"]), 2)
		self.assertEqual(out["unread"], 2)

	def test_category_and_unread_filters(self):
		feed.create_notification(TEAM, "srv", category="Server")
		feed.create_notification(TEAM, "bill", category="Billing")
		self.assertEqual(len(account.list_notifications(team=TEAM, category="Server")["items"]), 1)

	def test_mark_read_and_mark_all(self):
		a = feed.create_notification(TEAM, "A").name
		feed.create_notification(TEAM, "B")
		out = account.mark_notification_read(name=a, team=TEAM)
		self.assertEqual(out["unread"], 1)
		self.assertTrue(frappe.db.get_value("Team Notification", a, "is_read"))
		out = account.mark_all_notifications_read(team=TEAM)
		self.assertEqual(out["unread"], 0)
		self.assertEqual(feed.unread_count(TEAM), 0)

	def test_mark_read_rejects_other_teams_row(self):
		# A row belonging to another team can't be marked read via this team's scope.
		foreign = feed.create_notification(OTHER, "not yours").name
		with self.assertRaises(frappe.PermissionError):
			account.mark_notification_read(name=foreign, team=TEAM)


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
			"Team Notification", {"team": TEAM, "event_type": "Server Failed"}, ["severity", "category"]
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].severity, "Error")
		self.assertEqual(rows[0].category, "Server")
		frappe.db.delete("Asset", {"resource_id": "vm-feed-1"})
