# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from central.integrations.suite import SuiteClient

# A pool below its minimum gets a whole batch, not a top-up of one. One batch per run keeps
# the job short and the Suite site under its rate limit.
REFILL_BATCH_SIZE = 50


class MailService(Document):
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

	def get_client(self) -> SuiteClient:
		return SuiteClient(self)

	@property
	def available_mailbox_count(self) -> int:
		return frappe.db.count("Server Mailbox", {"mail_service": self.name, "status": "Available"})

	def refill(self) -> None:
		"""Create one batch of mailboxes when fewer than the minimum are available."""
		from central.infrastructure.doctype.server_mailbox.server_mailbox import ServerMailbox

		ServerMailbox.clean_up_pending(self)
		if self.available_mailbox_count >= self.minimum_available_mailboxes:
			return

		for _ in range(REFILL_BATCH_SIZE):
			try:
				ServerMailbox.provision(self)
			except Exception:
				# The next run retries; more calls now would only fail the same way.
				frappe.log_error(title=f"Mailbox creation failed for {self.name}")
				break


def refill_mailboxes() -> None:
	for name in frappe.get_all("Mail Service", filters={"enabled": 1}, pluck="name"):
		frappe.get_doc("Mail Service", name).refill()
