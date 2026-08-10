# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.iam import can, clear_grants_cache, user_has_operator_bypass


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
			self.append(
				"members",
				{"user": self.owner_user, "role": "Owner", "resource_type": "*", "status": "Active"},
			)

	def validate(self) -> None:
		self._validate_unique_members()
		self._validate_owner_membership()
		self._validate_role_scope()
		self._validate_changes()

	def on_update(self) -> None:
		# Team and member-row edits change resolved capabilities; drop the request-cached
		# grants so later checks in this request see the new state.
		clear_grants_cache()

	def on_trash(self) -> None:
		self._require_capability("team:delete")
		clear_grants_cache()

	# Internal; the HTTP surface is central.api.teams.invite_team_member.
	def invite_member(
		self,
		email: str,
		role: str,
		expires_in_days: int = 7,
		resource_type: str = "*",
		resource_name: str | None = None,
	) -> str:
		self._require_capability("team:manage_members")
		invitation = frappe.get_doc(
			{
				"doctype": "Team Invitation",
				"team": self.name,
				"email": email,
				"role": role,
				"expires_in_days": expires_in_days,
				"resource_type": resource_type or "*",
				"resource_name": resource_name,
			}
		)
		invitation.insert()
		return invitation.name

	# Internal; the HTTP surface is central.api.teams.set_team_member_roles.
	def set_member_roles(self, user: str, roles: list[dict]) -> None:
		"""Replace every non-Owner role grant `user` holds with `roles`, each a
		{role, resource_type, resource_name} dict. Full-replace, not incremental,
		to match the Manage Roles dialog's edit-then-save flow."""
		self._require_capability("team:manage_members")
		self._validate_member_change_target(user)
		if not roles:
			frappe.throw(_("A member must hold at least one role."))
		for grant in roles:
			if grant.get("role") == "Owner":
				frappe.throw(_("Use Transfer Ownership to assign the Owner role."))

		existing = self._get_member_rows(user)
		if not existing:
			frappe.throw(_("User {0} is not a member of this team.").format(user))
		status = existing[0].status

		for row in existing:
			self.remove(row)
		for grant in roles:
			self.append(
				"members",
				{
					"user": user,
					"role": grant["role"],
					"resource_type": grant.get("resource_type") or "*",
					"resource_name": grant.get("resource_name"),
					"status": status,
				},
			)
		self.save()

		from central.notification.engine import dispatch

		dispatch(
			team=self.name,
			event_type="role_change",
			message=", ".join(g["role"] for g in roles),
			affected_user=user,
		)

	# Internal; the HTTP surface is central.api.teams.set_team_member_status.
	def set_member_status(self, user: str, status: str) -> None:
		self._require_capability("team:manage_members")
		if status not in {"Active", "Suspended"}:
			frappe.throw(_("Invalid team member status."))
		self._validate_member_change_target(user)
		rows = self._get_member_rows(user)
		if not rows:
			frappe.throw(_("User {0} is not a member of this team.").format(user))
		for row in rows:
			row.status = status
		self.save()

	# Internal; the HTTP surface is central.api.teams.remove_team_member.
	def remove_member(self, user: str) -> None:
		self._require_capability("team:manage_members")
		self._validate_member_change_target(user)
		rows = self._get_member_rows(user)
		if not rows:
			frappe.throw(_("User {0} is not a member of this team.").format(user))
		for row in rows:
			self.remove(row)
		self.save()

	# Internal; the HTTP surface is central.api.teams.transfer_team_ownership.
	def transfer_ownership(self, user: str) -> None:
		"""Owner is exclusive: promoting `user` drops every role grant they held
		before, since Owner already covers everything those grants did."""
		self._require_current_owner()
		new_owner_rows = self._get_member_rows(user)
		if not any(row.status == "Active" for row in new_owner_rows):
			frappe.throw(_("The new owner must be an active team member."))

		current_owner_row = self._get_member(self.owner_user, role="Owner")
		current_owner_row.role = "Admin"

		for row in new_owner_rows:
			self.remove(row)
		self.append(
			"members",
			{"user": user, "role": "Owner", "resource_type": "*", "status": "Active"},
		)
		self.owner_user = user
		self.flags.transferring_ownership = True
		self.save()

	def add_member_from_invitation(
		self,
		user: str,
		role: str,
		resource_type: str = "*",
		resource_name: str | None = None,
	) -> None:
		if any(member.user == user for member in self.members):
			return
		self.append(
			"members",
			{
				"user": user,
				"role": role,
				"resource_type": resource_type or "*",
				"resource_name": None if (resource_type or "*") == "*" else resource_name,
				"status": "Active",
			},
		)
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
		grants = [
			(row.user, row.role, row.resource_type, row.resource_name) for row in self.members if row.user
		]
		if len(grants) != len(set(grants)):
			frappe.throw(_("A member cannot hold the same role on the same resource twice."))

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
		before = self._grants_by_user(previous)
		after = self._grants_by_user(self)

		if self.owner_user != previous.owner_user or before.get(previous.owner_user) != after.get(
			previous.owner_user
		):
			self._require_current_owner(previous.owner_user)

		for user in set(before) | set(after):
			changed = before.get(user) != after.get(user)
			if changed and user == frappe.session.user and not self.flags.transferring_ownership:
				frappe.throw(_("You cannot change your own team membership."), frappe.PermissionError)
			before_roles = {grant[0] for grant in before.get(user, frozenset())}
			after_roles = {grant[0] for grant in after.get(user, frozenset())}
			if changed and ("Owner" in before_roles or "Owner" in after_roles):
				self._require_current_owner(previous.owner_user)

	@staticmethod
	def _grants_by_user(doc) -> dict[str, frozenset]:
		grants: dict[str, set] = {}
		for member in doc.members:
			grants.setdefault(member.user, set()).add(
				(member.role, member.resource_type, member.resource_name, member.status)
			)
		return {user: frozenset(rows) for user, rows in grants.items()}

	def _validate_member_change_target(self, user: str) -> None:
		if user == frappe.session.user and not self._is_operator():
			frappe.throw(_("You cannot change your own team membership."), frappe.PermissionError)
		if user == self.owner_user:
			frappe.throw(_("Transfer ownership before changing the current owner."))

	def _get_member(self, user: str, role: str | None = None):
		for member in self.members:
			if member.user == user and (role is None or member.role == role):
				return member
		frappe.throw(_("User {0} is not a member of this team.").format(user))

	def _get_member_rows(self, user: str) -> list:
		return [member for member in self.members if member.user == user]

	def _require_capability(self, capability: str) -> None:
		if not self._is_operator() and not can(frappe.session.user, self.name, capability):
			frappe.throw(_("Not permitted for this team."), frappe.PermissionError)

	def _require_current_owner(self, owner_user: str | None = None) -> None:
		if not self._is_operator() and frappe.session.user != (owner_user or self.owner_user):
			frappe.throw(_("Only the current team owner can do this."), frappe.PermissionError)

	@staticmethod
	def _member_state(doc) -> list[tuple[str, str, str, str, str]]:
		return sorted(
			(member.user, member.role, member.resource_type, member.resource_name or "", member.status)
			for member in doc.members
		)

	@staticmethod
	def _is_operator() -> bool:
		return user_has_operator_bypass()
