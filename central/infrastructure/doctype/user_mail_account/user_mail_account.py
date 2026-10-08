# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime

from central.errors import throw_action_error

if TYPE_CHECKING:
	from central.infrastructure.doctype.frappemail_service.frappemail_service import FrappeMailService

# A mailbox still Pending after this long belongs to a refill run that did not finish.
PENDING_TIMEOUT_MINUTES = 15
SMTP_STARTTLS_PORT = 587
# Room the mailbox keys take in pilot-common-site-config, next to the Central Settings keys.
MAILBOX_CONFIG_BYTES = 400


class MailboxPoolEmpty(frappe.ValidationError):
	pass


class UserMailAccount(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assigned_at: DF.Datetime | None
		email: DF.Data
		frappemail_service: DF.Link
		password: DF.Password | None
		resource_action: DF.Link | None
		server: DF.Link | None
		status: DF.Literal["Pending", "Available", "Assigned", "Deleted"]
		team: DF.Link | None
	# end: auto-generated types

	@classmethod
	def provision(cls, service: FrappeMailService) -> UserMailAccount:
		"""Create a mailbox on the Suite site and add it to the service's pool."""
		mailbox = frappe.get_doc(
			{
				"doctype": "User Mail Account",
				"email": f"notifications-{secrets.token_hex(6)}@{service.domain}",
				"frappemail_service": service.name,
				"password": secrets.token_urlsafe(24),
			}
		).insert(ignore_permissions=True)
		# The record must outlive a failed call, so that clean_up_pending finds the mailbox.
		frappe.db.commit()

		service.create_send_only_member(mailbox.email, mailbox.get_password())
		mailbox.db_set("status", "Available", commit=True)
		return mailbox

	@classmethod
	def clean_up_pending(cls, service: FrappeMailService) -> None:
		"""Remove mailboxes that an interrupted refill may have left on the Suite site."""
		stale = frappe.get_all(
			"User Mail Account",
			filters={
				"frappemail_service": service.name,
				"status": "Pending",
				"creation": ("<", add_to_date(now_datetime(), minutes=-PENDING_TIMEOUT_MINUTES)),
			},
			pluck="name",
		)
		for name in stale:
			try:
				frappe.get_doc("User Mail Account", name).remove_from_suite_site()
			except Exception:
				# The record stays Pending, so the next run retries it.
				frappe.log_error(title=f"Removing pending mailbox {name} failed")

	@classmethod
	def assign(cls, action) -> UserMailAccount | None:
		"""Take a mailbox from the region's pool for a server creation. A retried creation gets the same one."""
		service = frappe.db.get_value("Region", action.region, "frappemail_service")
		if not service or not frappe.db.get_value("FrappeMail Service", service, "enabled"):
			return None

		if name := frappe.db.get_value("User Mail Account", {"resource_action": action.name}):
			return frappe.get_doc("User Mail Account", name)

		# skip_locked: two creations at once take two different mailboxes.
		name = frappe.db.get_value(
			"User Mail Account",
			{"frappemail_service": service, "status": "Available"},
			order_by="creation asc",
			for_update=True,
			skip_locked=True,
		)
		if not name:
			throw_action_error("MAILBOX_POOL_EMPTY", exc=MailboxPoolEmpty)

		mailbox = frappe.get_doc("User Mail Account", name)
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
			"mail_server": frappe.db.get_value("FrappeMail Service", self.frappemail_service, "smtp_server"),
			# Fixed to 587 with STARTTLS for now; later this follows the endpoints the mail server publishes.
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
		frappe.db.set_value("User Mail Account", {"resource_action": resource_action}, "server", server)

	@classmethod
	def queue_removal(cls, **filters) -> None:
		"""Remove the assigned mailboxes that match, such as those of one server or one failed creation."""
		for name in frappe.get_all(
			"User Mail Account", filters={**filters, "status": "Assigned"}, pluck="name"
		):
			frappe.enqueue(
				"central.infrastructure.doctype.user_mail_account.user_mail_account.remove_mailbox",
				name=name,
				enqueue_after_commit=True,
			)

	def remove_from_suite_site(self) -> None:
		frappe.get_doc("FrappeMail Service", self.frappemail_service).delete_member(self.email)
		self.db_set("status", "Deleted", commit=True)


def remove_mailbox(name: str) -> None:
	frappe.get_doc("User Mail Account", name).remove_from_suite_site()
