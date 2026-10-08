# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime

if TYPE_CHECKING:
	from central.infrastructure.doctype.mail_service.mail_service import MailService

# A mailbox still Pending after this long belongs to a refill run that did not finish.
PENDING_TIMEOUT_MINUTES = 15
SMTP_STARTTLS_PORT = 587


class MailboxPoolEmpty(frappe.ValidationError):
	pass


class ServerMailbox(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assigned_at: DF.Datetime | None
		email: DF.Data
		mail_service: DF.Link
		password: DF.Password | None
		resource_action: DF.Link | None
		server: DF.Link | None
		status: DF.Literal["Pending", "Available", "Assigned", "Deleted"]
		team: DF.Link | None
	# end: auto-generated types

	@classmethod
	def provision(cls, service: MailService) -> ServerMailbox:
		"""Create a mailbox on the Suite site and add it to the service's pool."""
		mailbox = frappe.get_doc(
			{
				"doctype": "Server Mailbox",
				"email": f"notifications-{secrets.token_hex(6)}@{service.domain}",
				"mail_service": service.name,
				"password": secrets.token_urlsafe(24),
			}
		).insert(ignore_permissions=True)
		# The record must outlive a failed call, so that clean_up_pending finds the mailbox.
		frappe.db.commit()

		service.get_client().create_send_only_member(mailbox.email, mailbox.get_password())
		mailbox.db_set("status", "Available", commit=True)
		return mailbox

	@classmethod
	def clean_up_pending(cls, service: MailService) -> None:
		"""Remove mailboxes that an interrupted refill may have left on the Suite site."""
		stale = frappe.get_all(
			"Server Mailbox",
			filters={
				"mail_service": service.name,
				"status": "Pending",
				"creation": ("<", add_to_date(now_datetime(), minutes=-PENDING_TIMEOUT_MINUTES)),
			},
			pluck="name",
		)
		for name in stale:
			frappe.get_doc("Server Mailbox", name).remove_from_suite_site()

	@classmethod
	def assign(cls, action) -> ServerMailbox | None:
		"""Take a mailbox from the region's pool for a server creation. A retried creation gets the same one."""
		service = frappe.db.get_value("Region", action.region, "mail_service")
		if not service or not frappe.db.get_value("Mail Service", service, "enabled"):
			return None

		if name := frappe.db.get_value("Server Mailbox", {"resource_action": action.name}):
			return frappe.get_doc("Server Mailbox", name)

		# skip_locked: two creations at once take two different mailboxes.
		name = frappe.db.get_value(
			"Server Mailbox",
			{"mail_service": service, "status": "Available"},
			order_by="creation asc",
			for_update=True,
			skip_locked=True,
		)
		if not name:
			frappe.throw(
				_("Mail service {0} has no mailbox ready. Try again in a few minutes.").format(service),
				MailboxPoolEmpty,
			)

		mailbox = frappe.get_doc("Server Mailbox", name)
		mailbox.db_set(
			{
				"status": "Assigned",
				"resource_action": action.name,
				"team": action.team,
				"assigned_at": now_datetime(),
			}
		)
		return mailbox

	def get_site_config(self) -> dict:
		"""The common_site_config keys that make Pilot and every site send through this mailbox."""
		return {
			"mail_server": frappe.db.get_value("Mail Service", self.mail_service, "smtp_server"),
			# A site reads its mail account from common_site_config, which can only use STARTTLS.
			"mail_port": SMTP_STARTTLS_PORT,
			"use_tls": 1,
			"mail_login": self.email,
			"mail_password": self.get_password(),
			"auto_email_id": self.email,
			# The mail server refuses a sender address that is not the login.
			"always_use_account_email_id_as_sender": 1,
		}

	@classmethod
	def link_server(cls, resource_action: str, server: str) -> None:
		frappe.db.set_value("Server Mailbox", {"resource_action": resource_action}, "server", server)

	@classmethod
	def queue_removal(cls, server: str) -> None:
		for name in frappe.get_all(
			"Server Mailbox", filters={"server": server, "status": "Assigned"}, pluck="name"
		):
			frappe.enqueue(
				"central.infrastructure.doctype.server_mailbox.server_mailbox.remove_mailbox",
				name=name,
				enqueue_after_commit=True,
			)

	def remove_from_suite_site(self) -> None:
		frappe.get_doc("Mail Service", self.mail_service).get_client().delete_member(self.email)
		self.db_set("status", "Deleted", commit=True)


def remove_mailbox(name: str) -> None:
	frappe.get_doc("Server Mailbox", name).remove_from_suite_site()
