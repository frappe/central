# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from central.identity.signup_email import clear_signup_domains


class SignupDomain(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		blocked_until: DF.Datetime | None
		domain: DF.Data
		reason: DF.SmallText
		source: DF.Literal["Manual", "Automatic"]
		status: DF.Literal["Blocked", "Trusted"]
	# end: auto-generated types

	def autoname(self):
		self.domain = (self.domain or "").strip().lower().removeprefix("@")
		self.name = self.domain

	def validate(self):
		if "@" in self.domain or "." not in self.domain:
			frappe.throw(_("Enter a domain such as example.edu, without a name or @."))

	def is_blocking(self) -> bool:
		if self.status != "Blocked":
			return False
		return not self.blocked_until or get_datetime(self.blocked_until) > now_datetime()

	def on_update(self):
		self.clear_cache_now_and_after_commit()

	def on_trash(self):
		self.clear_cache_now_and_after_commit()

	def clear_cache_now_and_after_commit(self):
		# A signup between the two clears can cache the old rows again.
		clear_signup_domains()
		frappe.db.after_commit.add(clear_signup_domains)
