# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import Self

import frappe
from frappe import _
from frappe.model.document import Document


class UserNotificationPreference(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		category: DF.Literal["Billing", "Server", "Team"]
		email_enabled: DF.Check
		in_app_enabled: DF.Check
		team: DF.Link
		user: DF.Link
	# end: auto-generated types

	@classmethod
	def upsert(cls, user: str, team: str, category: str, email_enabled: bool, in_app_enabled: bool) -> Self:
		"""Save one preference per user, team and category."""
		values = {"email_enabled": int(email_enabled), "in_app_enabled": int(in_app_enabled)}
		name = frappe.db.get_value(
			"User Notification Preference", {"user": user, "team": team, "category": category}
		)
		if name:
			doc = frappe.get_doc("User Notification Preference", name)
			doc.update(values)
			return doc.save()

		return frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": user,
				"team": team,
				"category": category,
				**values,
			}
		).insert()

	def validate(self):
		existing = frappe.db.exists(
			"User Notification Preference",
			{
				"user": self.user,
				"team": self.team,
				"category": self.category,
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(_("Preference for {0} already exists on this team").format(self.category))


def on_doctype_update() -> None:
	_remove_duplicate_preferences()
	frappe.db.add_unique("User Notification Preference", ["user", "team", "category"])


def _remove_duplicate_preferences() -> None:
	fields = ["name", "user", "team", "category"]
	rows = frappe.get_all("User Notification Preference", fields=fields, order_by="modified desc", limit=0)
	seen = set()
	duplicates = []
	for row in rows:
		key = (row.user, row.team, row.category)
		if key in seen:
			duplicates.append(row.name)
		else:
			seen.add(key)
	if duplicates:
		frappe.db.delete("User Notification Preference", {"name": ["in", duplicates]})
