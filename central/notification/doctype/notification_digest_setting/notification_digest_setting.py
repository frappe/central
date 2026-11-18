# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import Self

import frappe
from frappe import _
from frappe.model.document import Document


class NotificationDigestSetting(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		digest_hour: DF.Int
		team: DF.Link
		user: DF.Link
	# end: auto-generated types

	@classmethod
	def upsert(cls, user: str, team: str, digest_hour: int) -> Self:
		"""Save the one digest setting for a user and team."""
		cls._validate_hour_type(digest_hour)
		name = frappe.db.get_value("Notification Digest Setting", {"user": user, "team": team})
		if name:
			doc = frappe.get_doc("Notification Digest Setting", name)
			if doc.digest_hour == digest_hour:
				return doc

			doc.digest_hour = digest_hour
			return doc.save()

		return frappe.get_doc(
			{
				"doctype": "Notification Digest Setting",
				"user": user,
				"team": team,
				"digest_hour": digest_hour,
			}
		).insert()

	@classmethod
	def get_hour(cls, user: str, team: str) -> int:
		"""Return the saved hour, or the DocType default for a user with no row."""
		digest_hour = frappe.db.get_value(
			"Notification Digest Setting", {"user": user, "team": team}, "digest_hour"
		)
		return cls.default_hour() if digest_hour is None else digest_hour

	@classmethod
	def load_for_users(cls, team: str, users: list[str]) -> dict[str, int]:
		"""Read digest hours for many users in one query, with the default for missing rows."""
		if not users:
			return {}

		rows = frappe.get_all(
			"Notification Digest Setting",
			filters={"team": team, "user": ["in", users]},
			fields=["user", "digest_hour"],
			limit=0,
		)
		hours = {row.user: row.digest_hour for row in rows}
		default = cls.default_hour()
		return {user: hours.get(user, default) for user in users}

	@classmethod
	def default_hour(cls) -> int:
		"""The database default, so the form can show a value before the first save."""
		field = frappe.get_meta("Notification Digest Setting").get_field("digest_hour")
		return frappe.utils.cint(field.default)

	@staticmethod
	def _validate_hour_type(digest_hour: int) -> None:
		# Frappe casts Int fields to int, so reject a fractional value before it is truncated.
		if type(digest_hour) is not int:
			frappe.throw(_("Digest hour must be a whole hour from 0 to 23."))


def on_doctype_update() -> None:
	frappe.db.add_unique("Notification Digest Setting", ["user", "team"])
	frappe.db.add_index("Notification Digest Setting", ["team"])
