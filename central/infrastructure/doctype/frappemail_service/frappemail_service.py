# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import json

import frappe
import requests
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.user_mail_account.user_mail_account import (
	MAILBOX_CONFIG_BYTES,
	UserMailAccount,
)

ADMIN_API = "/api/method/suite.mail.api.admin."
TIMEOUT_SECONDS = (5, 60)
# The Suite site answers an unknown member and a refused caller with the same 403.
NOT_A_MEMBER = "is not a mail account"
# One batch per run keeps the job short and the Suite site under its rate limit.
REFILL_BATCH_SIZE = 50


class FrappeMailService(Document):
	"""A Suite site that holds server mailboxes, and the pool of them Central keeps ready."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data
		api_secret: DF.Password
		backup_email: DF.Data
		domain: DF.Data
		enabled: DF.Check
		minimum_available_mailboxes: DF.Int
		service_name: DF.Data
		site_url: DF.Data
		smtp_server: DF.Data
	# end: auto-generated types

	def validate(self) -> None:
		# Larger mail settings would make the region refuse every server creation.
		sample = UserMailAccount.build_site_config(
			self.smtp_server, *UserMailAccount.generate_credentials(self.domain)
		)
		if len(json.dumps(sample).encode()) > MAILBOX_CONFIG_BYTES:
			frappe.throw(_("Domain and SMTP Server are too long for the server metadata."))

	@property
	def available_mailbox_count(self) -> int:
		return frappe.db.count("User Mail Account", {"frappemail_service": self.name, "status": "Available"})

	def refill(self) -> None:
		"""Finish interrupted work, then add a batch when the pool is below its minimum."""
		UserMailAccount.clean_up_unfinished(self)
		if not self.enabled or self.available_mailbox_count >= self.minimum_available_mailboxes:
			return

		for _attempt in range(REFILL_BATCH_SIZE):
			try:
				UserMailAccount.provision(self)
			except Exception:
				frappe.log_error(title=f"Mailbox creation failed for {self.name}")
				break

	@frappe.whitelist(methods=["POST"])
	def queue_refill(self) -> None:
		self.check_permission("write")
		frappe.enqueue_doc(
			self.doctype, self.name, "refill", job_id=f"mailbox-refill:{self.name}", deduplicate=True
		)

	def create_send_only_member(self, email: str, password: str) -> None:
		username, domain = email.split("@", 1)
		self.post_to_suite_site(
			"add_member",
			{
				"username": username,
				"domain": domain,
				"first_name": username,
				"password": password,
				"backup_email": self.backup_email,
				"is_admin": False,
				"send_invite": False,
				"disable_receiving": True,
			},
		)

	def delete_member(self, email: str) -> None:
		"""Delete the member. A member the Suite site does not have counts as deleted."""
		try:
			self.post_to_suite_site("delete_members", {"names": [email]})
		except requests.HTTPError as error:
			if NOT_A_MEMBER not in error.response.text:
				raise

	def post_to_suite_site(self, method: str, payload: dict) -> None:
		# No redirects, so the token never reaches another host. A redirect then counts as a failure.
		response = requests.post(
			f"{self.site_url.rstrip('/')}{ADMIN_API}{method}",
			json=payload,
			headers={
				"Authorization": f"token {self.api_key}:{self.get_password('api_secret')}",
				"Accept": "application/json",
			},
			timeout=TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		if not 200 <= response.status_code < 300:
			raise requests.HTTPError(f"{response.status_code} from {method}", response=response)


def refill_mailboxes() -> None:
	"""Scheduler: refill every service. One service's failure does not stop the others."""
	for name in frappe.get_all("FrappeMail Service", pluck="name"):
		try:
			frappe.get_doc("FrappeMail Service", name).refill()
		except Exception:
			frappe.log_error(title=f"Mailbox refill failed for {name}")
