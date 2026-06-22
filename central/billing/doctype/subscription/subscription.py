# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Subscription(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account_standing: DF.Literal["Current", "Past Due", "Suspended"]
		asset_id: DF.Link | None
		billing_cycle: DF.Literal["Monthly", "Annual"]
		default_payment_method: DF.Link | None
		enabled: DF.Check
		gateway: DF.Link | None
		plan: DF.Link | None
		start_date: DF.Date | None
		team: DF.Link
	# end: auto-generated types

	def validate(self):
		self.validate_duplicate_subscription()

	def validate_duplicate_subscription(self):
		"""Block a second enabled subscription for the same team + asset.

		A team can hold at most one active subscription per asset; re-subscribing
		the same asset must go through `change_plan`/`cancel_subscription`, not a
		second Subscription doc.
		"""
		if not (self.enabled and self.team and self.asset_id):
			return

		duplicate = frappe.db.exists(
			"Subscription",
			{
				"name": ["!=", self.name],
				"team": self.team,
				"asset_id": self.asset_id,
				"enabled": 1,
			},
		)
		if duplicate:
			frappe.throw(
				f"Team {self.team} already has an active subscription ({duplicate}) for asset {self.asset_id}.",
				frappe.DuplicateEntryError,
			)

	def after_insert(self):
		"""Log a 'Created' Subscription Change on insert."""
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Created",
				"new_value": self.plan,
				"effective_at": frappe.utils.now_datetime(),
				"changed_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def on_update(self):
		if self.has_value_changed("plan"):
			self.log_plan_change()

	def log_plan_change(self):
		"""Log a 'Plan Changed' Subscription Change whenever plan is updated."""
		previous = self.get_doc_before_save()
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Plan Changed",
				"old_value": previous.plan if previous else None,
				"new_value": self.plan,
				"effective_at": frappe.utils.now_datetime(),
				"changed_by": self.flags.changed_by or frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def enable(self):
		"""Mark this subscription enabled and save."""
		self.enabled = 1
		self.save(ignore_permissions=True)

	def disable(self):
		"""Mark this subscription disabled and save."""
		self.enabled = 0
		self.save(ignore_permissions=True)
