# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe.model.document import Document

ADMIN_API = "/api/method/suite.mail.api.admin."
TIMEOUT_SECONDS = (5, 60)
# The Suite site refuses an unknown member with the same 403 as a refused caller; only the message differs.
NOT_A_MEMBER = "is not a mail account"

# A pool below its minimum gets a whole batch, not a top-up of one. One batch per run keeps
# the job short and the Suite site under its rate limit.
REFILL_BATCH_SIZE = 50


class FrappeMailService(Document):
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
				# Nobody reads a server's mailbox, so mail sent to it bounces.
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
		"""Call the Suite site's admin API as the Suite Admin this service names."""
		# No redirects: the token must not follow a Location header to another host.
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
		# A redirect is not a success: with redirects off it would otherwise pass as one.
		if not 200 <= response.status_code < 300:
			raise requests.HTTPError(f"{response.status_code} from {method}", response=response)

	@property
	def available_mailbox_count(self) -> int:
		return frappe.db.count("User Mail Account", {"frappemail_service": self.name, "status": "Available"})

	def refill(self) -> None:
		"""Create one batch of mailboxes when fewer than the minimum are available."""
		from central.infrastructure.doctype.user_mail_account.user_mail_account import UserMailAccount

		UserMailAccount.clean_up_pending(self)
		if self.available_mailbox_count >= self.minimum_available_mailboxes:
			return

		for _ in range(REFILL_BATCH_SIZE):
			try:
				UserMailAccount.provision(self)
			except Exception:
				# The next run retries; more calls now would only fail the same way.
				frappe.log_error(title=f"Mailbox creation failed for {self.name}")
				break


def refill_mailboxes() -> None:
	for name in frappe.get_all("FrappeMail Service", filters={"enabled": 1}, pluck="name"):
		try:
			frappe.get_doc("FrappeMail Service", name).refill()
		except Exception:
			# One service's failure must not stop the refill of the others.
			frappe.log_error(title=f"Mailbox refill failed for {name}")
