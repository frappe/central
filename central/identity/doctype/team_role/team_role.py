# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.iam import can, user_has_operator_bypass


class TeamRole(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.identity.doctype.role_capability.role_capability import RoleCapability

		capabilities: DF.Table[RoleCapability]
		is_system: DF.Check
		role_name: DF.Data
		team: DF.Link | None
	# end: auto-generated types

	def validate(self):
		if self.is_system and self.team:
			frappe.throw(_("System Team Roles must not be tied to a team."))
		if not self.is_system and not self.team:
			frappe.throw(_("Custom Team Roles must be tied to one team."))

	def on_trash(self) -> None:
		if self.is_system:
			frappe.throw(_("System Team Roles cannot be deleted."))
		if self.flags.from_team_delete:
			return
		if not user_has_operator_bypass() and not can(frappe.session.user, self.team, "team:manage_members"):
			frappe.throw(_("You can't manage roles for this team."), frappe.PermissionError)
		if frappe.db.exists("Team Member", {"role": self.name}):
			frappe.throw(_("Reassign members off this role before deleting it."), frappe.ValidationError)
		if frappe.db.exists("Team Invitation", {"role": self.name, "status": "Pending"}):
			frappe.throw(_("A pending invitation still uses this role."), frappe.ValidationError)
