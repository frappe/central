# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, now_datetime

from central.errors import throw_action_error

if TYPE_CHECKING:
	from central.infrastructure.doctype.frappemail_service.frappemail_service import FrappeMailService
	from central.infrastructure.doctype.resource_action.resource_action import ResourceAction

# A Pending or Removing mailbox older than this belongs to a run that did not finish.
UNFINISHED_TIMEOUT_MINUTES = 15
SMTP_STARTTLS_PORT = 587
# The share of pilot-common-site-config that the mailbox keys may take.
MAILBOX_CONFIG_BYTES = 400


class MailboxPoolEmpty(frappe.ValidationError):
	pass


class UserMailAccount(Document):
	"""One send-only Suite mailbox that a server sends its mail through."""

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
		status: DF.Literal["Pending", "Available", "Assigned", "Removing", "Deleted"]
		team: DF.Link | None
	# end: auto-generated types

	@classmethod
	def provision(cls, service: FrappeMailService) -> UserMailAccount:
		"""Create a mailbox on the Suite site and add it to the pool."""
		email, password = cls.generate_credentials(service.domain)
		mailbox = frappe.get_doc(
			{
				"doctype": "User Mail Account",
				"email": email,
				"password": password,
				"frappemail_service": service.name,
			}
		).insert(ignore_permissions=True)
		# Commit first, so that a failed call leaves a Pending record to clean up.
		frappe.db.commit()  # nosemgrep

		service.create_send_only_member(email, password)
		mailbox.db_set("status", "Available", commit=True)
		return mailbox

	@staticmethod
	def generate_credentials(domain: str) -> tuple[str, str]:
		return f"notifications-{secrets.token_hex(6)}@{domain}", secrets.token_urlsafe(24)

	@classmethod
	def clean_up_unfinished(cls, service: FrappeMailService) -> None:
		"""Remove mailboxes that an interrupted refill or removal left on the Suite site."""
		for name in frappe.get_all(
			"User Mail Account",
			filters={
				"frappemail_service": service.name,
				"status": ("in", ("Pending", "Removing")),
				"modified": ("<", add_to_date(now_datetime(), minutes=-UNFINISHED_TIMEOUT_MINUTES)),
			},
			pluck="name",
		):
			try:
				frappe.get_doc("User Mail Account", name).remove_from_suite_site()
			except Exception:
				frappe.log_error(title=f"Mailbox removal failed for {name}")

	@classmethod
	def assign(cls, action: ResourceAction) -> UserMailAccount | None:
		"""Take a mailbox from the region's pool. A retried creation keeps its mailbox."""
		service = frappe.db.get_value("Region", action.region, "frappemail_service")
		if not service or not frappe.db.get_value("FrappeMail Service", service, "enabled"):
			return None

		if name := frappe.db.get_value(
			"User Mail Account", {"resource_action": action.name, "status": "Assigned"}
		):
			return frappe.get_doc("User Mail Account", name)

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
		"""The common_site_config keys that send Pilot and site mail through this mailbox."""
		smtp_server = frappe.db.get_value("FrappeMail Service", self.frappemail_service, "smtp_server")
		return self.build_site_config(smtp_server, self.email, self.get_password())

	@staticmethod
	def build_site_config(smtp_server: str, email: str, password: str) -> dict:
		return {
			"mail_server": smtp_server,
			# Fixed for now; later this follows the endpoints the mail server publishes.
			"mail_port": SMTP_STARTTLS_PORT,
			"use_tls": 1,
			"mail_login": email,
			"mail_password": password,
			"auto_email_id": email,
			# The mail server refuses a sender that is not the login.
			"always_use_account_email_id_as_sender": 1,
		}

	@classmethod
	def link_server(cls, resource_action: str, server: str) -> None:
		frappe.db.set_value(
			"User Mail Account", {"resource_action": resource_action, "status": "Assigned"}, "server", server
		)

	@classmethod
	def queue_removal(cls, **filters) -> None:
		"""Mark the matching assigned mailboxes Removing and queue their removal."""
		for name in frappe.get_all(
			"User Mail Account", filters={**filters, "status": "Assigned"}, pluck="name"
		):
			frappe.db.set_value("User Mail Account", name, "status", "Removing")
			frappe.enqueue(
				"central.infrastructure.doctype.user_mail_account.user_mail_account.remove_mailbox",
				name=name,
				enqueue_after_commit=True,
			)

	@frappe.whitelist(methods=["POST"])
	def revoke(self) -> None:
		self.check_permission("write")
		if self.status != "Assigned":
			frappe.throw(_("Only an assigned mailbox can be removed."))

		self.queue_removal(name=self.name)

	def remove_from_suite_site(self) -> None:
		frappe.get_doc("FrappeMail Service", self.frappemail_service).delete_member(self.email)
		self.db_set("status", "Deleted", commit=True)


def remove_mailbox(name: str) -> None:
	mailbox = frappe.get_doc("User Mail Account", name)
	if mailbox.status == "Removing":
		mailbox.remove_from_suite_site()
