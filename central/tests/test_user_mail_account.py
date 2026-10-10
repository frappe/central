import json
from unittest.mock import Mock, patch

import frappe
import requests
from frappe.tests import IntegrationTestCase

from central.infrastructure.doctype.user_mail_account.user_mail_account import (
	MailboxPoolEmpty,
	UserMailAccount,
	remove_mailbox,
)

MAILBOX = "central.infrastructure.doctype.user_mail_account.user_mail_account"
FRAPPEMAIL_SERVICE = "central.infrastructure.doctype.frappemail_service.frappemail_service"


def response(status: int, text: str = "") -> requests.Response:
	reply = requests.Response()
	reply.status_code = status
	reply._content = text.encode()
	return reply


def suite_reply(message) -> requests.Response:
	return response(200, json.dumps({"message": message}))


class TestServerMailbox(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)
		# Provisioning commits so a record outlives a failed call; tests roll back instead.
		self.enterContext(patch.object(frappe.db, "commit"))
		self.post = self.enterContext(
			patch(f"{FRAPPEMAIL_SERVICE}.requests.post", return_value=response(200))
		)
		self.service = frappe.get_doc(
			{
				"doctype": "FrappeMail Service",
				"service_name": frappe.generate_hash(length=8),
				"domain": "notifications.example.test",
				"smtp_server": "smtp.example.test",
				"smtp_port": 587,
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
				"frappemail_service": self.service.name,
			}
		).insert()

	def action(self, name: str = "action-1") -> Mock:
		action = Mock(region=self.region.name, team=None)
		action.name = name
		return action

	def statuses(self) -> list[str]:
		return frappe.get_all(
			"User Mail Account", filters={"frappemail_service": self.service.name}, pluck="status"
		)

	def test_refill_creates_only_the_missing_mailboxes(self):
		self.available_mailbox()

		self.service.refill()

		self.assertEqual(self.statuses(), ["Available"] * 3)
		payload = self.post.call_args.kwargs["json"]
		self.assertTrue(payload["username"].startswith("notifications-"))
		self.assertTrue(payload["disable_receiving"])
		self.assertFalse(payload["send_invite"])

	def test_refill_creates_at_most_one_batch(self):
		with patch(f"{FRAPPEMAIL_SERVICE}.REFILL_BATCH_SIZE", 2):
			self.service.refill()

		self.assertEqual(self.statuses(), ["Available"] * 2)

	def test_a_failed_creation_stops_the_batch_and_stays_pending(self):
		self.post.return_value = response(500)

		with patch(f"{FRAPPEMAIL_SERVICE}.frappe.log_error"):
			self.service.refill()

		self.assertEqual(self.statuses(), ["Pending"])

	def test_a_stale_pending_mailbox_is_removed_from_the_suite_site(self):
		mailbox = self.pending_mailbox()
		self.post.return_value = response(403, '{"exception": "x is not a mail account."}')

		UserMailAccount.clean_up_unfinished(self.service)

		self.assertEqual(mailbox.reload().status, "Deleted")
		self.assertTrue(self.post.call_args.args[0].endswith("delete_members"))

	def test_a_refused_deletion_keeps_the_mailbox_pending(self):
		mailbox = self.pending_mailbox()
		self.post.return_value = response(403, '{"exception": "Not permitted"}')

		with patch(f"{MAILBOX}.frappe.log_error") as log_error:
			UserMailAccount.clean_up_unfinished(self.service)

		log_error.assert_called_once()

		self.assertEqual(mailbox.reload().status, "Pending")

	def test_a_server_takes_a_mailbox_and_a_retry_gets_the_same_one(self):
		first, second = self.available_mailbox(), self.available_mailbox()

		taken = UserMailAccount.assign(self.action())
		retried = UserMailAccount.assign(self.action())
		other = UserMailAccount.assign(self.action("action-2"))

		self.assertEqual(taken.name, first.name)
		self.assertEqual(retried.name, first.name)
		self.assertEqual(other.name, second.name)
		self.assertEqual(first.reload().status, "Assigned")

	def test_a_retry_after_a_failure_gets_a_new_mailbox(self):
		first, second = self.available_mailbox(), self.available_mailbox()
		UserMailAccount.assign(self.action())

		with patch(f"{MAILBOX}.frappe.enqueue"):
			UserMailAccount.queue_removal(resource_action="action-1", server=("is", "not set"))
		retried = UserMailAccount.assign(self.action())

		self.assertEqual(first.reload().status, "Removing")
		self.assertEqual(retried.name, second.name)

	def test_an_empty_pool_fails_the_creation(self):
		with self.assertRaises(MailboxPoolEmpty):
			UserMailAccount.assign(self.action())

	def test_a_region_without_a_frappemail_service_gets_no_mailbox(self):
		self.region.db_set("frappemail_service", None)

		self.assertIsNone(UserMailAccount.assign(self.action()))

	def test_a_disabled_frappemail_service_gives_no_mailbox(self):
		self.service.db_set("enabled", 0)
		self.available_mailbox()

		self.assertIsNone(UserMailAccount.assign(self.action()))

	def test_sites_send_through_the_mailbox_over_starttls(self):
		mailbox = self.available_mailbox()

		config = mailbox.get_site_config()

		self.assertEqual(config["mail_server"], "smtp.example.test")
		self.assertEqual((config["mail_port"], config["use_tls"], config["use_ssl"]), (587, 1, 0))
		self.assertEqual((config["mail_login"], config["auto_email_id"]), (mailbox.email, mailbox.email))
		self.assertEqual(config["mail_password"], mailbox.get_password())

	def test_sites_send_over_ssl_on_port_465(self):
		self.service.db_set("smtp_port", 465)

		config = self.available_mailbox().get_site_config()

		self.assertEqual((config["mail_port"], config["use_tls"], config["use_ssl"]), (465, 0, 1))

	def test_a_new_service_takes_the_starttls_endpoint_from_the_suite_site(self):
		endpoints = [
			{"protocol": "IMAP", "hostname": "imap.example.test", "port": 993},
			{"protocol": "SMTP", "hostname": "ssl.example.test", "port": 465},
			{"protocol": "SMTP", "hostname": "tls.example.test", "port": 587},
		]
		with patch(f"{FRAPPEMAIL_SERVICE}.requests.get", return_value=suite_reply(endpoints)):
			service = self.new_service()

		self.assertEqual((service.smtp_server, service.smtp_port), ("tls.example.test", 587))

	def test_a_new_service_fails_without_a_published_smtp_endpoint(self):
		endpoints = [{"protocol": "SMTP", "hostname": "smtp.example.test", "port": 2525}]
		with (
			patch(f"{FRAPPEMAIL_SERVICE}.requests.get", return_value=suite_reply(endpoints)),
			self.assertRaisesRegex(frappe.ValidationError, "no SMTP endpoint"),
		):
			self.new_service()

	def test_an_unsupported_smtp_port_is_refused(self):
		self.service.smtp_port = 2525

		with self.assertRaisesRegex(frappe.ValidationError, "465 .* or 587"):
			self.service.save()

	def new_service(self):
		return frappe.get_doc(
			{
				"doctype": "FrappeMail Service",
				"service_name": frappe.generate_hash(length=8),
				"domain": "notifications.example.test",
				"site_url": "https://suite.example.test",
				"api_key": "key",
				"api_secret": "secret",
				"backup_email": "ops@example.test",
			}
		).insert()

	def test_a_terminated_server_queues_its_mailbox_removal(self):
		self.available_mailbox()
		UserMailAccount.assign(self.action())
		UserMailAccount.link_server("action-1", "server-1")

		with patch(f"{MAILBOX}.frappe.enqueue") as enqueue:
			UserMailAccount.queue_removal(server="server-1")

		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(self.statuses(), ["Removing"])

	def test_an_operator_can_remove_an_available_mailbox(self):
		mailbox = self.available_mailbox()

		with patch(f"{MAILBOX}.frappe.enqueue") as enqueue:
			mailbox.revoke()

		enqueue.assert_called_once()
		self.assertEqual(mailbox.reload().status, "Removing")

	def test_a_mailbox_is_deleted_only_after_its_removal(self):
		mailbox = self.available_mailbox()

		with self.assertRaises(frappe.ValidationError):
			mailbox.delete()

		mailbox.db_set("status", "Deleted")
		mailbox.delete()

		self.assertFalse(frappe.db.exists("User Mail Account", mailbox.name))

	def test_a_removal_job_skips_a_mailbox_no_longer_queued_for_removal(self):
		mailbox = self.available_mailbox()
		self.post.reset_mock()

		remove_mailbox(mailbox.name)

		self.post.assert_not_called()
		self.assertEqual(mailbox.reload().status, "Available")

	def test_a_disabled_service_still_retries_a_failed_removal_but_creates_none(self):
		mailbox = self.stale(self.available_mailbox())
		mailbox.db_set("status", "Removing", update_modified=False)
		self.service.db_set("enabled", 0)
		self.post.reset_mock()

		self.service.refill()

		self.assertEqual(mailbox.reload().status, "Deleted")
		self.post.assert_called_once()

	def available_mailbox(self) -> UserMailAccount:
		return UserMailAccount.provision(self.service)

	def pending_mailbox(self) -> UserMailAccount:
		mailbox = frappe.get_doc(
			{
				"doctype": "User Mail Account",
				"email": f"notifications-{frappe.generate_hash(length=6)}@notifications.example.test",
				"frappemail_service": self.service.name,
				"password": "password",
			}
		).insert()
		return self.stale(mailbox)

	def stale(self, mailbox: UserMailAccount) -> UserMailAccount:
		mailbox.db_set("modified", "2026-01-01 00:00:00", update_modified=False)
		return mailbox
