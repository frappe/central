# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PaymentMethod(Document):
	def validate(self):
		self._reject_duplicate_card()
		self._validate_billing_group()

	def _validate_billing_group(self):
		"""A method may only be earmarked to one of its own team's active groups —
		same reasoning as Subscription.validate_billing_group: a foreign or disabled
		group would silently mean nothing (routing would just never match it), so
		refuse the tag outright rather than let someone believe a card is dedicated
		to a group when it is not."""
		if not self.billing_group:
			return
		group = frappe.db.get_value(
			"Billing Group", self.billing_group, ["team", "enabled"], as_dict=True
		)
		if not group:
			return  # a broken link — Frappe's own link validation reports it better
		if group.team != self.team:
			frappe.throw(
				f"Billing Group {self.billing_group} belongs to team {group.team}, not {self.team}.",
			)
		if not group.enabled:
			frappe.throw(
				f"Billing Group {self.billing_group} is disabled; a method can't be earmarked to it.",
			)

	def _reject_duplicate_card(self):
		"""A team can't register the same card twice. Using one card as both the
		primary and a backup gives no real fallback, so it is disallowed."""
		if not self.gateway_method_id or self.status == "Cancelled":
			return
		dup = frappe.get_all(
			"Payment Method",
			filters={
				"team": self.team,
				"gateway_method_id": self.gateway_method_id,
				"status": ["!=", "Cancelled"],
				"name": ["!=", self.name or ""],
			},
			limit=1,
		)
		if dup:
			frappe.throw(
				_(
					"This card is already on file for the team — the same card can't be "
					"used as both the primary and a backup method."
				),
				frappe.ValidationError,
			)
