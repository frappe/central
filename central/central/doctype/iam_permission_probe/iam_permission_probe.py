# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now

from central.iam import can, get_effective_permissions


class IAMPermissionProbe(Document):

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed: DF.Check
		capability: DF.Link
		last_checked_at: DF.Datetime | None
		resolved_grants: DF.Code | None
		team: DF.Link
		user: DF.Link
	# end: auto-generated types

	def validate(self):
		self.evaluate(save=False)

	@frappe.whitelist()
	def evaluate(self, save: bool = True) -> dict:
		self.allowed = 1 if can(self.user, self.team, self.capability) else 0
		self.last_checked_at = now()
		self.resolved_grants = frappe.as_json(get_effective_permissions(self.user, self.team), indent=2)
		if save:
			self.save()
		return {
			"allowed": bool(self.allowed),
			"grants": frappe.parse_json(self.resolved_grants),
		}
