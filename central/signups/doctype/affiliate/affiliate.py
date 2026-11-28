# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.sso import central_url


class Affiliate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		code: DF.Data | None
		enabled: DF.Check
		naming_series: DF.Literal["AFF-.#####"]
		status: DF.Literal["Active", "Paused"]
		user: DF.Link
	# end: auto-generated types

	@classmethod
	def get_user_affiliate(cls, user: str) -> frappe._dict | None:
		"""The user's affiliate with its share link, or None when the user never joined."""
		affiliate = frappe.db.get_value(
			"Affiliate",
			{"user": user},
			["code", "status", "enabled"],
			as_dict=True,
		)
		if affiliate:
			affiliate.link = f"{central_url()}/r/{affiliate.code}"
		return affiliate

	@classmethod
	def set_membership(cls, user: str, joined: bool) -> None:
		"""Joining creates the user's affiliate or makes it Active again. Leaving pauses it.
		An affiliate that an operator disabled cannot join again."""
		name = frappe.db.get_value("Affiliate", {"user": user})
		if not name:
			if joined:
				cls.create_for_user(user)
			return

		affiliate = frappe.get_doc("Affiliate", name)
		if joined and not affiliate.enabled:
			frappe.throw(
				_("Frappe paused your affiliate link. Contact support to turn it on again."),
				frappe.PermissionError,
			)

		affiliate.status = "Active" if joined else "Paused"
		# The user changes only the status of their own affiliate.
		affiliate.save(ignore_permissions=True)

	@classmethod
	def create_for_user(cls, user: str) -> None:
		try:
			# Affiliate is System Manager only. The user joins only for themselves.
			frappe.get_doc({"doctype": "Affiliate", "user": user}).insert(ignore_permissions=True)
		except frappe.UniqueValidationError:
			# A second join at the same moment: the first one already created it as Active.
			# Any other clash, such as on the random code, is a real failure.
			if not frappe.db.exists("Affiliate", {"user": user}):
				raise
			frappe.clear_last_message()

	def validate(self) -> None:
		# A disabled affiliate is always paused, however it is saved. Enabling it again leaves
		# it paused, so the user turns the link on themselves.
		if not self.enabled:
			self.status = "Paused"

	def before_insert(self) -> None:
		# The code goes in the share link, so it is random and set once. The ID is a series.
		self.code = frappe.generate_hash(length=10)
