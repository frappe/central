# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.iam import can, user_has_operator_bypass


class Team(Document):

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.central.doctype.team_member.team_member import TeamMember

		members: DF.Table[TeamMember]
		naming_series: DF.Literal["TEAM-.#####"]
		owner_user: DF.Link
		status: DF.Literal["Active", "Suspended"]
		team_name: DF.Data
	# end: auto-generated types

	def before_validate(self) -> None:
		if not self.is_new():
			return
		self.owner_user = self.owner_user or frappe.session.user
		if not any(member.user == self.owner_user for member in self.members):
			self.append("members", {"user": self.owner_user, "role": "Owner", "status": "Active"})

	def validate(self) -> None:
		self._validate_unique_members()
		self._validate_owner_membership()
		self._validate_role_scope()
		self._validate_changes()

	def on_trash(self) -> None:
		self._require_capability("team:delete")

	@frappe.whitelist(methods=["POST"])
	def invite_member(self, email: str, role: str, expires_in_days: int = 7) -> str:
		self._require_capability("team:manage_members")
		invitation = frappe.get_doc(
			{
				"doctype": "Team Invitation",
				"team": self.name,
				"email": email,
				"role": role,
				"expires_in_days": expires_in_days,
			}
		)
		invitation.insert()
		return invitation.name

	@frappe.whitelist(methods=["POST"])
	def set_member_role(self, user: str, role: str) -> None:
		self._require_capability("team:manage_members")
		self._validate_member_change_target(user, role)
		self._get_member(user).role = role
		self.save()

		from central.notification.engine import dispatch
		dispatch(
			team=self.name,
			event_type="role_change",
			message=role,
			affected_user=user,
		)

	@frappe.whitelist(methods=["POST"])
	def set_member_status(self, user: str, status: str) -> None:
		self._require_capability("team:manage_members")
		if status not in {"Active", "Suspended"}:
			frappe.throw(_("Invalid team member status."))
		self._validate_member_change_target(user)
		self._get_member(user).status = status
		self.save()

	@frappe.whitelist(methods=["POST"])
	def remove_member(self, user: str) -> None:
		self._require_capability("team:manage_members")
		self._validate_member_change_target(user)
		self.remove(self._get_member(user))
		self.save()

	@frappe.whitelist(methods=["POST"])
	def transfer_ownership(self, user: str) -> None:
		self._require_current_owner()
		new_owner = self._get_member(user)
		if new_owner.status != "Active":
			frappe.throw(_("The new owner must be an active team member."))

		current_owner = self._get_member(self.owner_user)
		current_owner.role = "Admin"
		new_owner.role = "Owner"
		self.owner_user = user
		self.flags.transferring_ownership = True
		self.save()

	def add_member_from_invitation(self, user: str, role: str) -> None:
		if any(member.user == user for member in self.members):
			return
		self.append("members", {"user": user, "role": role, "status": "Active"})
		self.flags.from_team_invitation = True
		# The accepted invitation authorizes this write before the invitee is a member.
		self.save(ignore_permissions=True)

		from central.notification.engine import dispatch
		dispatch(
			team=self.name,
			event_type="member_joined",
			message=user,
		)

	def _validate_unique_members(self) -> None:
		users = [row.user for row in self.members if row.user]
		if len(users) != len(set(users)):
			frappe.throw(_("A user can appear only once in a team."))

	def _validate_owner_membership(self) -> None:
		if not self.owner_user:
			return

		owners = [row for row in self.members if row.role == "Owner"]
		if len(owners) == 1 and owners[0].user == self.owner_user and owners[0].status == "Active":
			return

		frappe.throw(_("A team must have exactly one active Owner member matching Owner User."))

	def _validate_role_scope(self) -> None:
		for member in self.members:
			role_team, is_system = frappe.db.get_value("Team Role", member.role, ["team", "is_system"]) or (
				None,
				0,
			)
			if not is_system and role_team != self.name:
				frappe.throw(_("Team Role {0} does not belong to this team.").format(member.role))

	def _validate_changes(self) -> None:
		if self.is_new() or self.flags.from_team_invitation or self._is_operator():
			if (
				self.is_new()
				and not self.flags.from_user_bootstrap
				and not self._is_operator()
				and self.owner_user != frappe.session.user
			):
				frappe.throw(_("A new team must be owned by the user creating it."), frappe.PermissionError)
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		if self._metadata_changed(previous):
			self._require_capability("team:edit")
		if self._members_changed(previous):
			self._require_capability("team:manage_members")
			self._validate_sensitive_member_changes(previous)

	def _metadata_changed(self, previous) -> bool:
		return self.team_name != previous.team_name or self.status != previous.status

	def _members_changed(self, previous) -> bool:
		return self.owner_user != previous.owner_user or self._member_state(self) != self._member_state(
			previous
		)

	def _validate_sensitive_member_changes(self, previous) -> None:
		before = {member.user: (member.role, member.status) for member in previous.members}
		after = {member.user: (member.role, member.status) for member in self.members}

		if self.owner_user != previous.owner_user or before.get(previous.owner_user) != after.get(
			previous.owner_user
		):
			self._require_current_owner(previous.owner_user)

		for user in set(before) | set(after):
			changed = before.get(user) != after.get(user)
			if changed and user == frappe.session.user and not self.flags.transferring_ownership:
				frappe.throw(_("You cannot change your own team membership."), frappe.PermissionError)
			before_role = before.get(user, (None, None))[0]
			after_role = after.get(user, (None, None))[0]
			if changed and (before_role == "Owner" or after_role == "Owner"):
				self._require_current_owner(previous.owner_user)

	def _validate_member_change_target(self, user: str, role: str | None = None) -> None:
		if user == frappe.session.user and not self._is_operator():
			frappe.throw(_("You cannot change your own team membership."), frappe.PermissionError)
		if user == self.owner_user:
			frappe.throw(_("Transfer ownership before changing the current owner."))
		if role == "Owner":
			frappe.throw(_("Use Transfer Ownership to assign the Owner role."))

	def _get_member(self, user: str):
		for member in self.members:
			if member.user == user:
				return member
		frappe.throw(_("User {0} is not a member of this team.").format(user))

	def _require_capability(self, capability: str) -> None:
		if not self._is_operator() and not can(frappe.session.user, self.name, capability):
			frappe.throw(_("Not permitted for this team."), frappe.PermissionError)

	def _require_current_owner(self, owner_user: str | None = None) -> None:
		if not self._is_operator() and frappe.session.user != (owner_user or self.owner_user):
			frappe.throw(_("Only the current team owner can do this."), frappe.PermissionError)

	@staticmethod
	def _member_state(doc) -> list[tuple[str, str, str]]:
		return sorted((member.user, member.role, member.status) for member in doc.members)

	@staticmethod
	def _is_operator() -> bool:
		return user_has_operator_bypass()
