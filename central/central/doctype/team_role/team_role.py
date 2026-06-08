# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TeamRole(Document):

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from central.central.doctype.role_capability.role_capability import RoleCapability
		from frappe.types import DF

		capabilities: DF.Table[RoleCapability]
		is_system: DF.Check
		role_name: DF.Data
		team: DF.Link | None
	# end: auto-generated types

	def validate(self):
		if self.is_system and self.team:
			frappe.throw("System Team Roles must not be tied to a team.")
		if not self.is_system and not self.team:
			frappe.throw("Custom Team Roles must be tied to one team.")

	def on_trash(self):
		if self.is_system:
			frappe.throw("System Team Roles cannot be deleted.")
