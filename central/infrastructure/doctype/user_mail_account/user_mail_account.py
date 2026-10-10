# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import secrets
from typing import TYPE_CHECKING, Self

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
# Supported SMTP submission ports and whether each uses SSL/TLS, in order of preference.
SMTP_PORTS = {587: False, 465: True}


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
	def provision(cls, service: FrappeMailService) -> Self:
		"""Create a mailbox on the Suite site and add it to the pool."""
		email = f"notifications-{secrets.token_hex(6)}@{service.domain}"
		password = secrets.token_urlsafe(24)
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
	def assign(cls, action: ResourceAction) -> Self | None:
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
		server, port = frappe.db.get_value(
			"FrappeMail Service", self.frappemail_service, ["smtp_server", "smtp_port"]
		)
		if not server or port not in SMTP_PORTS:
			frappe.throw(
				_("FrappeMail Service {0} has no valid SMTP endpoint. Use Refresh SMTP Info.").format(
					self.frappemail_service
				)
			)
		is_ssl = SMTP_PORTS[port]
		return {
			"mail_server": server,
			"mail_port": port,
			"use_ssl": int(is_ssl),
			"use_tls": int(not is_ssl),
			"mail_login": self.email,
			"mail_password": self.get_password(),
			"auto_email_id": self.email,
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
		"""Mark the matching ready or assigned mailboxes Removing and queue their removal."""
		for name in frappe.get_all(
			"User Mail Account",
			filters={**filters, "status": ("in", ("Available", "Assigned"))},
			pluck="name",
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
		if self.status not in ("Available", "Assigned"):
			frappe.throw(_("Only an available or assigned mailbox can be removed."))

		self.queue_removal(name=self.name)

	def on_trash(self) -> None:
		# A record must outlive its Suite member, so that a failed removal is retried.
		if self.status != "Deleted":
			frappe.throw(_("Use Remove Mailbox. Only a deleted mailbox record can be deleted."))

	def remove_from_suite_site(self) -> None:
		frappe.get_doc("FrappeMail Service", self.frappemail_service).delete_member(self.email)
		self.db_set("status", "Deleted", commit=True)


def remove_mailbox(name: str) -> None:
	mailbox = frappe.get_doc("User Mail Account", name)
	if mailbox.status == "Removing":
		mailbox.remove_from_suite_site()
