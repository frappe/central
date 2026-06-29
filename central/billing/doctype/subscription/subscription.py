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
		cluster: DF.ReadOnly | None
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
		"""Log a 'Created' Subscription Change, with a rate snapshot, on insert.

		The segment opens at the subscription's start_date (when billing begins),
		not the wall-clock insert time, so a backdated subscription bills its real
		period."""
		rate, currency = self.resolve_rate_snapshot()
		effective_at = (
			frappe.utils.get_datetime(self.start_date) if self.start_date else frappe.utils.now_datetime()
		)
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Created",
				"new_value": self.plan,
				"locked_rate": rate,
				"currency": currency,
				"effective_at": effective_at,
				"changed_by": frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def on_update(self):
		# on_update fires during the initial insert too; after_insert already logs the
		# 'Created' segment, so only log a plan change on a genuine later edit.
		if not self.flags.in_insert and self.has_value_changed("plan"):
			self.log_plan_change()

	def log_plan_change(self):
		"""Log a 'Plan Changed' Subscription Change, with a fresh rate snapshot."""
		previous = self.get_doc_before_save()
		rate, currency = self.resolve_rate_snapshot()
		frappe.get_doc(
			{
				"doctype": "Subscription Change",
				"subscription": self.name,
				"change_type": "Plan Changed",
				"old_value": previous.plan if previous else None,
				"new_value": self.plan,
				"locked_rate": rate,
				"currency": currency,
				"effective_at": frappe.utils.now_datetime(),
				"changed_by": self.flags.changed_by or frappe.session.user,
			}
		).insert(ignore_permissions=True)

	def resolve_rate_snapshot(self) -> tuple[float | None, str | None]:
		"""The catalog rate + currency to snapshot onto a Subscription Change now.

		Billing reads this snapshot forever for the segment it opens — never the
		live catalog rate — so re-resolving it later must not change past charges.
		"""
		if not self.plan:
			return None, None
		currency = frappe.db.get_value("Billing Profile", self.team, "currency")
		if not currency:
			return None, None
		cluster = frappe.db.get_value("Asset", self.asset_id, "cluster") if self.asset_id else None
		rate = frappe.get_doc("Plan", self.plan).get_rate(currency, cluster)
		return rate, currency

	def enable(self):
		"""Mark this subscription enabled and save."""
		self.enabled = 1
		self.save(ignore_permissions=True)

	def disable(self):
		"""Mark this subscription disabled and save."""
		self.enabled = 0
		self.save(ignore_permissions=True)


def create_subscription(asset_id: str):
	"""Create an enabled Subscription for an Asset, using its team + plan."""
	asset = frappe.get_doc("Asset", asset_id)
	return frappe.get_doc(
		{
			"doctype": "Subscription",
			"team": asset.team,
			"asset_id": asset.name,
			"plan": asset.plan,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
