# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# The record each scoped grant names. A site grant applies to the server the site runs on.
RESOURCE_DOCTYPES = {"Server": "Virtual Machine", "Site": "Site"}


class TeamMember(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		resource_name: DF.Data | None
		resource_type: DF.Literal["*", "Server", "Site"]
		role: DF.Link
		status: DF.Literal["Active", "Invited", "Suspended"]
		user: DF.Link
	# end: auto-generated types

	def validate_resource(self, team: str) -> None:
		"""A row grants its role on every resource, or on one server or site of `team`.
		The Owner role is always team-wide."""
		if self.role == "Owner" and (self.resource_type or "*") != "*":
			frappe.throw(_("The Owner role applies to all resources."))
		validate_resource_scope(self, team)


def validate_resource_scope(grant, team: str) -> None:
	"""Where a Team Member row or a Team Invitation applies: every resource, or one server
	or site that belongs to `team`."""
	grant.resource_type = grant.resource_type or "*"
	if grant.resource_type == "*":
		grant.resource_name = None
		return

	doctype = RESOURCE_DOCTYPES.get(grant.resource_type)
	if not doctype:
		frappe.throw(_("Invalid resource type."))
	if not grant.resource_name:
		frappe.throw(_("Select the {0} this role applies to.").format(_(grant.resource_type).lower()))
	if frappe.db.get_value(doctype, grant.resource_name, "team") != team:
		frappe.throw(
			_("{0} {1} does not belong to this team.").format(_(grant.resource_type), grant.resource_name)
		)
