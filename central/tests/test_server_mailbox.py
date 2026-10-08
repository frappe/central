import json
from unittest.mock import Mock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.server_mailbox.server_mailbox import MailboxPoolEmpty, ServerMailbox

MAILBOX = "central.infrastructure.doctype.server_mailbox.server_mailbox"
MAIL_SERVICE = "central.infrastructure.doctype.mail_service.mail_service"
SUITE = "central.integrations.suite"


def response(status: int, text: str = "") -> requests.Response:
	reply = requests.Response()
	reply.status_code = status
	reply._content = text.encode()
	return reply


class TestServerMailbox(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		# Provisioning commits so a record outlives a failed call; tests roll back instead.
		self.enterContext(patch.object(frappe.db, "commit"))
		self.post = self.enterContext(patch(f"{SUITE}.requests.post", return_value=response(200)))
		self.service = frappe.get_doc(
			{
				"doctype": "Mail Service",
				"service_name": frappe.generate_hash(length=8),
				"domain": "notifications.example.test",
				"smtp_server": "smtp.example.test",
				"minimum_available_mailboxes": 3,
				"site_url": "https://suite.example.test",
				"api_key": "key",
				"api_secret": "secret",
				"backup_email": "ops@example.test",
			}
		).insert()
		self.region = frappe.get_doc(
			{
				"doctype": "Region",
				"region": frappe.generate_hash(length=8),
				"status": "Active",
				"mail_service": self.service.name,
			}
		).insert()

	def action(self, name: str = "action-1") -> Mock:
		action = Mock(region=self.region.name, team=None)
		action.name = name
		return action

	def statuses(self) -> list[str]:
		return frappe.get_all("Server Mailbox", filters={"mail_service": self.service.name}, pluck="status")

	def test_refill_creates_a_whole_batch_below_the_minimum(self):
		with patch(f"{MAIL_SERVICE}.REFILL_BATCH_SIZE", 5):
			self.service.refill()

		self.assertEqual(self.statuses(), ["Available"] * 5)
		payload = self.post.call_args.kwargs["json"]
		self.assertTrue(payload["username"].startswith("notifications-"))
		self.assertTrue(payload["disable_receiving"])
		self.assertFalse(payload["send_invite"])

	def test_refill_does_nothing_at_the_minimum(self):
		with patch(f"{MAIL_SERVICE}.REFILL_BATCH_SIZE", 3):
			self.service.refill()
		self.post.reset_mock()

		self.service.refill()

		self.post.assert_not_called()

	def test_a_failed_creation_stops_the_batch_and_stays_pending(self):
		self.post.return_value = response(500)

		with patch(f"{MAIL_SERVICE}.frappe.log_error"):
			self.service.refill()

		self.assertEqual(self.statuses(), ["Pending"])

	def test_a_stale_pending_mailbox_is_removed_from_the_suite_site(self):
		mailbox = self.pending_mailbox()
		self.post.return_value = response(403, '{"exception": "x is not a mail account."}')

		ServerMailbox.clean_up_pending(self.service)

		self.assertEqual(mailbox.reload().status, "Deleted")
		self.assertTrue(self.post.call_args.args[0].endswith("delete_members"))

	def test_a_refused_deletion_keeps_the_mailbox_pending(self):
		mailbox = self.pending_mailbox()
		self.post.return_value = response(403, '{"exception": "Not permitted"}')

		with self.assertRaises(requests.HTTPError):
			ServerMailbox.clean_up_pending(self.service)

		self.assertEqual(mailbox.reload().status, "Pending")

	def test_a_server_takes_a_mailbox_and_a_retry_gets_the_same_one(self):
		first, second = self.available_mailbox(), self.available_mailbox()

		taken = ServerMailbox.assign(self.action())
		retried = ServerMailbox.assign(self.action())
		other = ServerMailbox.assign(self.action("action-2"))

		self.assertEqual(taken.name, first.name)
		self.assertEqual(retried.name, first.name)
		self.assertEqual(other.name, second.name)
		self.assertEqual(first.reload().status, "Assigned")

	def test_an_empty_pool_fails_the_creation(self):
		with self.assertRaises(MailboxPoolEmpty):
			ServerMailbox.assign(self.action())

	def test_a_region_without_a_mail_service_gets_no_mailbox(self):
		self.region.db_set("mail_service", None)

		self.assertIsNone(ServerMailbox.assign(self.action()))

	def test_a_disabled_mail_service_gives_no_mailbox(self):
		self.service.db_set("enabled", 0)
		self.available_mailbox()

		self.assertIsNone(ServerMailbox.assign(self.action()))

	def test_sites_send_through_the_mailbox_over_starttls(self):
		mailbox = self.available_mailbox()

		config = mailbox.get_site_config()

		self.assertEqual(config["mail_server"], "smtp.example.test")
		self.assertEqual((config["mail_port"], config["use_tls"]), (587, 1))
		self.assertEqual(config["mail_login"], mailbox.email)
		self.assertEqual(config["auto_email_id"], mailbox.email)
		self.assertEqual(config["mail_password"], mailbox.get_password())
		self.assertEqual(config["always_use_account_email_id_as_sender"], 1)
		self.assertLessEqual(len(json.dumps(config)), 1024)

	def test_a_terminated_server_queues_its_mailbox_removal(self):
		self.available_mailbox()
		ServerMailbox.assign(self.action())
		ServerMailbox.link_server("action-1", "server-1")

		with patch(f"{MAILBOX}.frappe.enqueue") as enqueue:
			ServerMailbox.queue_removal("server-1")

		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def available_mailbox(self) -> ServerMailbox:
		return ServerMailbox.provision(self.service)

	def pending_mailbox(self) -> ServerMailbox:
		mailbox = frappe.get_doc(
			{
				"doctype": "Server Mailbox",
				"email": f"notifications-{frappe.generate_hash(length=6)}@notifications.example.test",
				"mail_service": self.service.name,
				"password": "password",
			}
		).insert()
		mailbox.db_set("creation", "2026-01-01 00:00:00")
		return mailbox
