# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from typing import Self

import frappe
from frappe import _
from frappe.model.document import Document

from central.notification import FREQUENCIES


class UserNotificationPreference(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.notification.doctype.notification_event_preference.notification_event_preference import (
			NotificationEventPreference,
		)

		category: DF.Literal["Billing", "Server", "Team", "Trial"]
		digest_hour: DF.Int
		email_enabled: DF.Check
		events: DF.Table[NotificationEventPreference]
		frequency: DF.Literal["Instant", "Daily", "Weekly"]
		in_app_enabled: DF.Check
		last_digest_at: DF.Datetime | None
		team: DF.Link
		user: DF.Link
	# end: auto-generated types

	@classmethod
	def upsert(
		cls,
		user: str,
		team: str,
		category: str,
		email_enabled: bool,
		in_app_enabled: bool,
		frequency: str = "Instant",
		digest_hour: int = 8,
		events: list[dict] | None = None,
	) -> Self:
		"""Save one preference per user, team and category."""
		values = {
			"email_enabled": int(email_enabled),
			"in_app_enabled": int(in_app_enabled),
			"frequency": frequency,
			"digest_hour": digest_hour,
		}
		name = frappe.db.get_value(
			"User Notification Preference", {"user": user, "team": team, "category": category}
		)
		if name:
			doc = frappe.get_doc("User Notification Preference", name)
			doc.update(values)
			if events is not None:
				doc.set("events", events)
			return doc.save()

		return frappe.get_doc(
			{
				"doctype": "User Notification Preference",
				"user": user,
				"team": team,
				"category": category,
				"events": events or [],
				**values,
			}
		).insert()

	@classmethod
	def load_for_users(cls, team: str, users: list[str]) -> dict[tuple[str, str], dict]:
		"""Read preferences for many users in one go. Engine and scheduler share this read."""
		if not users:
			return {}

		rows = frappe.get_all(
			"User Notification Preference",
			filters={"team": team, "user": ["in", users]},
			fields=[
				"name",
				"user",
				"category",
				"email_enabled",
				"in_app_enabled",
				"frequency",
				"digest_hour",
			],
			limit=0,
		)
		children = frappe.get_all(
			"Notification Event Preference",
			filters={
				"parent": ["in", [row.name for row in rows]],
				"parenttype": "User Notification Preference",
			},
			fields=["parent", "event_type", "email_enabled"],
			limit=0,
		)
		overrides = {}
		for child in children:
			overrides.setdefault(child.parent, {})[child.event_type] = bool(child.email_enabled)

		return {
			(row.user, row.category): {
				"email_enabled": bool(row.email_enabled),
				"in_app_enabled": bool(row.in_app_enabled),
				"frequency": row.frequency or "Instant",
				"digest_hour": 8 if row.digest_hour is None else row.digest_hour,
				"events": overrides.get(row.name, {}),
			}
			for row in rows
		}

	def validate(self):
		self.frequency = self.frequency or "Instant"
		self.digest_hour = frappe.utils.cint(self.digest_hour)
		if self.frequency not in FREQUENCIES:
			frappe.throw(_("Unsupported email frequency {0}.").format(frappe.bold(self.frequency)))
		if not 0 <= self.digest_hour <= 23:
			frappe.throw(_("Digest hour must be between 0 and 23."))
		if self.frequency == "Instant" or not self.email_enabled:
			self.last_digest_at = None
		elif not self.last_digest_at:
			self.last_digest_at = frappe.utils.now_datetime()
		self._validate_events()
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

	def on_update(self):
		# A member who leaves the digest still gets what was waiting for it.
		before = self.get_doc_before_save()
		if before and before.last_digest_at and self.frequency == "Instant" and self.email_enabled:
			frappe.enqueue(
				"central.notification.digest.send_digest",
				user=self.user,
				team=self.team,
				since={self.category: before.last_digest_at},
				frequency=before.frequency,
				enqueue_after_commit=True,
			)

	def _validate_events(self) -> None:
		names = [row.event_type for row in self.events]
		if len(names) != len(set(names)):
			frappe.throw(_("Each event can appear only once."))
		rows = frappe.get_all(
			"Notification Event Type",
			filters={"name": ["in", names]},
			fields=["name", "category"],
			as_list=True,
		)
		categories = dict(rows)
		for event_type in names:
			category = categories.get(event_type)
			if not category:
				frappe.throw(_("Unknown notification event {0}.").format(frappe.bold(event_type)))
			if category != self.category:
				frappe.throw(
					_("Event {0} belongs to {1}, not {2}.").format(
						frappe.bold(event_type), frappe.bold(category), frappe.bold(self.category)
					)
				)


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
