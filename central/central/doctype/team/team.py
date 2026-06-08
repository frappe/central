# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Team(Document):

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from central.central.doctype.team_member.team_member import TeamMember
		from frappe.types import DF

		members: DF.Table[TeamMember]
		naming_series: DF.Literal["TEAM-.#####"]
		owner_user: DF.Link
		status: DF.Literal["Active", "Suspended"]
		team_name: DF.Data
	# end: auto-generated types

	def validate(self):
		self._validate_unique_members()
		self._validate_owner_membership()

	def _validate_unique_members(self):
		users = [row.user for row in self.members if row.user]
		if len(users) != len(set(users)):
			frappe.throw("A user can appear only once in a team.")

	def _validate_owner_membership(self):
		if not self.owner_user:
			return

		for row in self.members:
			if row.user == self.owner_user and row.role == "Owner" and row.status == "Active":
				return

		frappe.throw("The owner user must be an active Team Member with the Owner role.")
