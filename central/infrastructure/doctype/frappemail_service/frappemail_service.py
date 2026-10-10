# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.user_mail_account.user_mail_account import SMTP_PORTS, UserMailAccount

ADMIN_API = "/api/method/suite.mail.api.admin."
CLIENT_CONFIG_API = "/api/method/suite.mail.api.account.get_mail_client_config"
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
		smtp_port: DF.Int
		smtp_server: DF.Data | None
	# end: auto-generated types

	def before_insert(self) -> None:
		if not (self.smtp_server and self.smtp_port):
			self.set_smtp_endpoint()

	def validate(self) -> None:
		if self.smtp_port and self.smtp_port not in SMTP_PORTS:
			frappe.throw(_("SMTP Port must be 465 (SSL/TLS) or 587 (STARTTLS)."))

	@frappe.whitelist(methods=["POST"])
	def refresh_smtp_info(self) -> None:
		self.check_permission("write")
		self.set_smtp_endpoint()
		self.save()

	def set_smtp_endpoint(self) -> None:
		"""Take the SMTP endpoint the Suite site publishes. STARTTLS wins, as every Frappe version supports it."""
		endpoints = {
			endpoint["port"]: endpoint["hostname"]
			for endpoint in self.get_from_suite_site(CLIENT_CONFIG_API)
			if endpoint.get("protocol") == "SMTP"
		}
		port = next((port for port in SMTP_PORTS if port in endpoints), None)
		if not port:
			frappe.throw(
				_(
					"The Suite site publishes no SMTP endpoint on port 587 or 465. "
					"Turn on the mail client configuration in its Mail Settings."
				)
			)
		self.smtp_server, self.smtp_port = endpoints[port], port

	@property
	def available_mailbox_count(self) -> int:
		return frappe.db.count("User Mail Account", {"frappemail_service": self.name, "status": "Available"})

	def refill(self) -> None:
		"""Finish interrupted work, then create the mailboxes the pool is missing, up to one batch."""
		UserMailAccount.clean_up_unfinished(self)
		if not self.enabled:
			return

		missing = self.minimum_available_mailboxes - self.available_mailbox_count
		for _attempt in range(min(missing, REFILL_BATCH_SIZE)):
			try:
				UserMailAccount.provision(self)
			except Exception:
				frappe.log_error(title=f"Mailbox creation failed for {self.name}")
				break

	@frappe.whitelist(methods=["POST"])
	def queue_refill(self) -> None:
		self.check_permission("write")
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"refill",
			job_id=f"mailbox-refill:{self.name}",
			deduplicate=True,
			enqueue_after_commit=True,
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
			headers=self.suite_site_headers,
			timeout=TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		if not 200 <= response.status_code < 300:
			raise requests.HTTPError(f"{response.status_code} from {method}", response=response)

	def get_from_suite_site(self, path: str) -> list | dict:
		response = requests.get(
			f"{self.site_url.rstrip('/')}{path}",
			headers=self.suite_site_headers,
			timeout=TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		if not 200 <= response.status_code < 300:
			raise requests.HTTPError(f"{response.status_code} from {path}", response=response)
		return response.json()["message"]

	@property
	def suite_site_headers(self) -> dict:
		return {
			"Authorization": f"token {self.api_key}:{self.get_password('api_secret')}",
			"Accept": "application/json",
		}


def refill_mailboxes() -> None:
	"""Scheduler: refill every service. One service's failure does not stop the others."""
	for name in frappe.get_all("FrappeMail Service", pluck="name"):
		try:
			frappe.get_doc("FrappeMail Service", name).refill()
		except Exception:
			frappe.log_error(title=f"Mailbox refill failed for {name}")
