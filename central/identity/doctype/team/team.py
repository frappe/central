# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from central.billing import settings as billing_settings
from central.iam import can, clear_grants_cache, user_has_operator_bypass
from central.identity.doctype.team.tenant import (
	allocate_tenant_id,
	prepare_tenant_id_series,
	validate_tenant_id,
)

# The order the console shows them in lives in dashboard/src/components/onboarding/steps.ts.
ONBOARDING_STEPS = ("invite", "billing", "start")
# Each invitation sends an email, so one request may send only this many.
MAX_INVITATIONS_PER_REQUEST = 10


class Team(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.identity.doctype.team_member.team_member import TeamMember
		from central.identity.doctype.team_onboarding_step.team_onboarding_step import TeamOnboardingStep

		is_staging_trial: DF.Check
		landing_product: DF.Link | None
		members: DF.Table[TeamMember]
		naming_series: DF.Literal["TEAM-.#####"]
		onboarding_steps: DF.Table[TeamOnboardingStep]
		owner_user: DF.Link
		referrer: DF.SmallText | None
		status: DF.Literal["Active", "Suspended"]
		team_logo: DF.AttachImage | None
		team_name: DF.Data
		tenant_id: DF.Int
		utm_campaign: DF.Data | None
		utm_medium: DF.Data | None
		utm_source: DF.Data | None
	# end: auto-generated types

	@classmethod
	def create_for_current_user(cls, team_name: str, attribution: dict | None = None) -> "Team":
		"""Create a team the signed-in user owns, with the signup's first-touch attribution.

		Only the user's first team gets billing provisioned when it is created. A later
		team gets its billing when its owner completes the billing profile. Welcome
		credits are granted once per owner, in grant_welcome_credits."""
		is_first_team = not frappe.db.exists("Team", {"owner_user": frappe.session.user})
		team = frappe.get_doc({"doctype": "Team", "team_name": team_name, **(attribution or {})}).insert()
		if is_first_team:
			team.provision_billing()
		return team

	def provision_billing(self) -> None:
		"""Seed the billing currency from the request IP and grant the welcome credits.

		A failure is logged and is not fatal. The owner can still complete the billing
		profile in the console, which provisions the same way."""
		from central.billing.payments.provisioning import provision_signup_billing
		from central.geo import get_country_from_ip

		try:
			provision_signup_billing(self.name, get_country_from_ip())
		except Exception:
			frappe.log_error(title="Team billing provisioning failed")

	def before_validate(self) -> None:
		if not self.is_new():
			return
		self.owner_user = self.owner_user or frappe.session.user
		if not any(member.user == self.owner_user for member in self.members):
			self.append(
				"members",
				{"user": self.owner_user, "role": "Owner", "resource_type": "*", "status": "Active"},
			)

	def before_insert(self) -> None:
		# A caller cannot choose another customer's network identity or a free trial.
		self.tenant_id = allocate_tenant_id()
		self.is_staging_trial = int(billing_settings.provision_teams_as_trial())
		# The trial flag is System Manager only (permlevel 1), and Frappe would reset it to its
		# default for any other creator. Central sets it here, so the creator's level does not apply.
		self.flags.ignore_permlevel_for_fields = ["is_staging_trial"]
		self._add_onboarding_steps()

	def _add_onboarding_steps(self) -> None:
		# A staging trial gets a placeholder billing profile, so it has no billing step.
		for step in ONBOARDING_STEPS:
			if step == "billing" and self.is_staging_trial:
				continue
			self.append("onboarding_steps", {"step": step, "status": "Pending"})

	def validate(self) -> None:
		self._validate_tenant_id_unchangeable()
		self._absorb_wildcard_grants()
		self._validate_unique_members()
		self._validate_owner_membership()
		self._validate_role_scope()
		self._validate_member_resources()
		self._validate_changes()
		self._validate_team_logo()

	def _validate_team_logo(self) -> None:
		"""The logo must be a file uploaded to this team's logo field, not any URL."""
		if not self.team_logo or not self.has_value_changed("team_logo"):
			return

		is_uploaded = frappe.db.exists(
			"File",
			{
				"file_url": self.team_logo,
				"attached_to_doctype": "Team",
				"attached_to_name": self.name,
				"attached_to_field": "team_logo",
			},
		)
		if not is_uploaded:
			frappe.throw(_("Upload the image again."))

	def on_update(self) -> None:
		# Team and member-row edits change resolved capabilities; drop the request-cached
		# grants so later checks in this request see the new state.
		clear_grants_cache()

	def on_trash(self) -> None:
		self._require_capability("team:delete")
		self._validate_no_owned_resources()
		self._delete_owned_access_records()
		clear_grants_cache()

	def _validate_no_owned_resources(self) -> None:
		for doctype in ("Virtual Machine", "Site"):
			if frappe.db.exists(doctype, {"team": self.name}):
				frappe.throw(
					_("Remove this team's servers and sites before deleting it."),
					frappe.ValidationError,
				)

	def _delete_owned_access_records(self) -> None:
		for name in frappe.get_all("Team Invitation", {"team": self.name}, pluck="name"):
			# Team deletion already passed team:delete and owns this dependent cleanup.
			frappe.delete_doc("Team Invitation", name, ignore_permissions=True, force=True)
		for name in frappe.get_all("Team Role", {"team": self.name, "is_system": 0}, pluck="name"):
			role = frappe.get_doc("Team Role", name)
			role.flags.from_team_delete = True
			# Team deletion already passed team:delete and owns this dependent cleanup.
			role.delete(ignore_permissions=True, force=True)

	# Internal; the HTTP surface is central.api.teams.invite_team_member.
	def invite_member(
		self,
		email: str,
		role: str,
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
				"resource_type": resource_type or "*",
				"resource_name": resource_name,
			}
		)
		invitation.insert()
		return invitation.name

	# Internal; the HTTP surface is central.api.teams.invite_team_member with `invitations`.
	def invite_members(self, invitations: list[dict]) -> list[dict]:
		"""Invite up to MAX_INVITATIONS_PER_REQUEST people, one invitation each.

		A refused row returns its error, and the other rows are still invited."""
		self._require_capability("team:manage_members")
		if not invitations:
			frappe.throw(_("Add at least one person to invite."))
		if len(invitations) > MAX_INVITATIONS_PER_REQUEST:
			frappe.throw(_("You can invite up to {0} people at a time.").format(MAX_INVITATIONS_PER_REQUEST))
		return [self._invite_one_of_many(row) for row in invitations]

	def _invite_one_of_many(self, row: dict) -> dict:
		email = row.get("email")
		if not isinstance(email, str) or not email.strip() or not row.get("role"):
			return {"email": email, "invitation": None, "error": _("Email and role are required.")}

		frappe.db.savepoint("team_invitation")
		try:
			name = self.invite_member(
				email,
				row.get("role"),
				resource_type=row.get("resource_type") or "*",
				resource_name=row.get("resource_name"),
			)
		except frappe.ValidationError as error:
			frappe.db.rollback(save_point="team_invitation")
			# The refusal is returned on its row, so it must not also show as a message.
			frappe.clear_last_message()
			return {"email": email, "invitation": None, "error": str(error)}

		frappe.db.release_savepoint("team_invitation")
		return {"email": email, "invitation": name, "error": None}

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

	# Internal; the HTTP surface is central.api.teams.leave_team.
	def leave(self) -> None:
		"""Drop your own membership. Leaving is yours to do, so it needs no
		capability — but the owner can't: transfer ownership or delete the team."""
		user = frappe.session.user
		if user == self.owner_user:
			frappe.throw(_("Transfer ownership before leaving this team."))
		rows = self._get_member_rows(user)
		if not rows:
			frappe.throw(_("You are not a member of this team."))
		for row in rows:
			self.remove(row)
		# A plain member holds no write permission on the Team doc; _validate_changes
		# is the real gate and allows this diff only because it is a self-removal.
		self.save(ignore_permissions=True)

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

	def set_onboarding_step(self, step: str, status: str) -> None:
		"""Record that the owner finished or skipped one onboarding step."""
		self._require_current_owner()
		if status not in {"Done", "Skipped"}:
			frappe.throw(_("Invalid onboarding step status."))
		row = next((row for row in self.onboarding_steps if row.step == step), None)
		if not row:
			frappe.throw(_("This team has no onboarding step {0}.").format(step))

		self._update_onboarding_step(row, status)
		self.save()

	def skip_onboarding(self) -> None:
		"""Skip every onboarding step the owner has not answered yet."""
		self._require_current_owner()
		for row in self.onboarding_steps:
			if row.status == "Pending":
				self._update_onboarding_step(row, "Skipped")
		self.save()

	@staticmethod
	def _update_onboarding_step(row, status: str) -> None:
		row.status = status
		row.updated_by = frappe.session.user
		row.updated_on = now_datetime()

	def _absorb_wildcard_grants(self) -> None:
		"""A role granted on all resources ("*") subsumes the same role on any
		specific resource, so holding both is contradictory — the narrow row
		grants nothing and reads as less access than the member actually has.
		Saves normalize silently: the wildcard stays, its shadowed rows go."""
		wildcards = self._wildcard_keys(self)
		shadowed = [row for row in self.members if self._is_shadowed(row, wildcards)]
		for row in shadowed:
			self.remove(row)

	@staticmethod
	def _wildcard_keys(doc) -> set[tuple[str, str]]:
		return {(row.user, row.role) for row in doc.members if row.resource_type == "*"}

	@staticmethod
	def _is_shadowed(row, wildcards: set[tuple[str, str]]) -> bool:
		return row.resource_type != "*" and (row.user, row.role) in wildcards

	@staticmethod
	def _effective_grants(doc) -> list:
		"""Member rows minus the ones a wildcard grant absorbs — the state a save
		normalizes to. Change detection compares this on both sides, so dropping
		rows that were already shadowed in storage doesn't read as a member edit
		and block a metadata-only save for someone without team:manage_members."""
		wildcards = Team._wildcard_keys(doc)
		return [row for row in doc.members if not Team._is_shadowed(row, wildcards)]

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

	def _validate_member_resources(self) -> None:
		"""Check the scope of each row this save adds or changes. A saved row may name a
		server removed since; it grants nothing and must not block other edits."""
		previous = self.get_doc_before_save()
		saved = {self._grant_key(row) for row in previous.members} if previous else set()
		for row in self.members:
			if self._grant_key(row) not in saved:
				row.validate_resource(self.name)

	@staticmethod
	def _grant_key(row) -> tuple:
		return (row.user, row.role, row.resource_type or "*", row.resource_name or None)

	def _validate_changes(self) -> None:
		if self.is_new() or self.flags.from_team_invitation or self._is_operator():
			if self.is_new() and not self._is_operator() and self.owner_user != frappe.session.user:
				frappe.throw(_("A new team must be owned by the user creating it."), frappe.PermissionError)
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		if self._metadata_changed(previous):
			self._require_capability("team:edit")
		if self._onboarding_state(self) != self._onboarding_state(previous):
			self._require_current_owner(previous.owner_user)
		if self._members_changed(previous) and not self._is_self_removal(previous):
			self._require_capability("team:manage_members")
			self._validate_sensitive_member_changes(previous)

	def _validate_tenant_id_unchangeable(self) -> None:
		validate_tenant_id(self.tenant_id)
		if not self.is_new() and self.has_value_changed("tenant_id"):
			frappe.throw(_("The tenant ID cannot be changed."), frappe.CannotChangeConstantError)

	def _metadata_changed(self, previous) -> bool:
		return self.team_name != previous.team_name or self.status != previous.status

	def _members_changed(self, previous) -> bool:
		return self.owner_user != previous.owner_user or self._member_state(self) != self._member_state(
			previous
		)

	def _is_self_removal(self, previous) -> bool:
		"""The entire member diff is the caller dropping their own rows: leaving.
		Anything else rides the normal team:manage_members gate."""
		user = frappe.session.user
		if self.owner_user != previous.owner_user or user == previous.owner_user:
			return False
		before = self._grants_by_user(previous)
		after = self._grants_by_user(self)
		if user not in before or user in after:
			return False
		del before[user]
		return before == after

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
		for member in Team._effective_grants(doc):
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
	def _onboarding_state(doc) -> list[tuple[str, str]]:
		return [(row.step, row.status) for row in doc.onboarding_steps]

	@staticmethod
	def _member_state(doc) -> list[tuple[str, str, str, str, str]]:
		return sorted(
			(member.user, member.role, member.resource_type, member.resource_name or "", member.status)
			for member in Team._effective_grants(doc)
		)

	@staticmethod
	def _is_operator() -> bool:
		return user_has_operator_bypass()


def on_doctype_update() -> None:
	prepare_tenant_id_series()
	# Model sync precedes the data patch that fills legacy zero values.
	if not frappe.db.exists("Team", {"tenant_id": 0}):
		frappe.db.add_unique("Team", ["tenant_id"])
