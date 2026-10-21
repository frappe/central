# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import secrets
import string
from typing import Self

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

CODE_LOOK_ALIKES = "0o1li"
CODE_ALPHABET = "".join(sorted(set(string.ascii_lowercase + string.digits) - set(CODE_LOOK_ALIKES)))
CODE_LENGTH = 8
CODE_ATTEMPTS = 5


class AffiliateStatusError(frappe.ValidationError):
	"""An affiliate request or review that the affiliate's current status does not allow."""


class Affiliate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		affiliate_code: DF.Data | None
		rejection_reason: DF.SmallText | None
		requested_on: DF.Datetime | None
		reviewed_by: DF.Link | None
		reviewed_on: DF.Datetime | None
		status: DF.Literal["Pending", "Active", "Rejected", "Disabled"]
		user: DF.Link
	# end: auto-generated types

	@classmethod
	def request_for(cls, user: str) -> Self:
		"""Ask for the user to become an affiliate. Safe to repeat."""
		name = frappe.db.get_value("Affiliate", {"user": user}, "name")
		if not name:
			return cls.create_request(user)

		affiliate = frappe.get_doc("Affiliate", name)
		if affiliate.status == "Rejected":
			# Lock only to write, so a repeated request does not block an operator.
			affiliate = frappe.get_doc("Affiliate", name, for_update=True)
			if affiliate.status == "Rejected":
				affiliate.ask_again()

		if affiliate.status == "Disabled":
			frappe.throw(_("Your affiliate account is paused."), AffiliateStatusError)

		return affiliate

	@classmethod
	def create_request(cls, user: str) -> Self:
		affiliate = frappe.get_doc({"doctype": "Affiliate", "user": user, "requested_on": now_datetime()})
		try:
			# An applicant holds no Affiliate permission and creates only their own request.
			return affiliate.insert(ignore_permissions=True)
		except frappe.UniqueValidationError:
			# A second request from the same user won the race. Drop Frappe's "must be unique" message,
			# and read the row with a lock, which sees the other request's committed row.
			frappe.clear_last_message()
			name = frappe.db.get_value("Affiliate", {"user": user}, "name", for_update=True)
			return frappe.get_doc("Affiliate", name)

	def ask_again(self) -> None:
		self.update(
			{
				"status": "Pending",
				"requested_on": now_datetime(),
				"reviewed_by": None,
				"reviewed_on": None,
				"rejection_reason": None,
			}
		)
		# An applicant holds no Affiliate permission and changes only their own request.
		self.save(ignore_permissions=True)

	def get_state(self) -> dict:
		"""What the affiliate sees about their own account."""
		return {
			"status": self.status,
			"affiliate_code": self.affiliate_code if self.status == "Active" else None,
			"rejection_reason": self.rejection_reason if self.status == "Rejected" else None,
		}

	@frappe.whitelist(methods=["POST"])
	def approve(self) -> None:
		"""Operator action: accept a pending request. The first approval sets the code."""
		frappe.only_for("System Manager")
		self.reload_for_update()
		if self.report_earlier_review():
			return

		self.require_status("Pending", _("Only a pending request can be approved."))
		self.affiliate_code = self.affiliate_code or generate_affiliate_code()
		self.record_review("Active")

	@frappe.whitelist(methods=["POST"])
	def reject(self, reason: str) -> None:
		"""Operator action: refuse a pending request. The applicant sees the reason."""
		frappe.only_for("System Manager")
		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("Give a reason for the rejection."))

		self.reload_for_update()
		if self.report_earlier_review():
			return

		self.require_status("Pending", _("Only a pending request can be rejected."))
		self.rejection_reason = reason
		self.record_review("Rejected")

	@frappe.whitelist(methods=["POST"])
	def disable(self) -> None:
		"""Operator action: pause an active affiliate until an operator enables it again."""
		frappe.only_for("System Manager")
		self.reload_for_update()
		self.require_status("Active", _("Only an active affiliate can be disabled."))
		self.status = "Disabled"
		self.save()

	@frappe.whitelist(methods=["POST"])
	def enable(self) -> None:
		"""Operator action: make a disabled affiliate active again, with the same code."""
		frappe.only_for("System Manager")
		self.reload_for_update()
		self.require_status("Disabled", _("Only a disabled affiliate can be enabled."))
		self.status = "Active"
		self.save()

	def reload_for_update(self) -> None:
		# Two operators can act at once, so each action reads the row under a lock.
		self.flags.for_update = True
		self.reload()

	def report_earlier_review(self) -> bool:
		"""Tell this operator who already decided, and whether anyone did."""
		if self.status == "Active":
			message = _("Already approved by {0}.")
		elif self.status == "Rejected":
			message = _("Already rejected by {0}.")
		else:
			return False

		frappe.msgprint(message.format(self.reviewed_by))
		return True

	def require_status(self, status: str, message: str) -> None:
		if self.status != status:
			frappe.throw(message, AffiliateStatusError)

	def record_review(self, status: str) -> None:
		self.update({"status": status, "reviewed_by": frappe.session.user, "reviewed_on": now_datetime()})
		self.save()

	def before_validate(self) -> None:
		# The unique index allows many NULLs but only one empty string, so an unset code is NULL.
		self.affiliate_code = (self.affiliate_code or "").strip().lower() or None

	def validate(self) -> None:
		previous = self.get_doc_before_save()
		if previous and previous.affiliate_code and self.has_value_changed("affiliate_code"):
			frappe.throw(_("The affiliate code cannot change after it is set."))


def generate_affiliate_code() -> str:
	"""A random code that no saved affiliate or named link has, because both share /r/. If a
	concurrent save takes the same code first, its unique index refuses this save."""
	for _attempt in range(CODE_ATTEMPTS):
		code = "".join(secrets.choice(CODE_ALPHABET) for _position in range(CODE_LENGTH))
		if not frappe.db.exists("Affiliate", {"affiliate_code": code}) and not frappe.db.exists(
			"Affiliate Link", code
		):
			return code

	frappe.throw(_("Could not create a unique affiliate code. Try again."))
