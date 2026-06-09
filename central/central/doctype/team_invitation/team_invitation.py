# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from contextlib import suppress

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	format_date,
	get_fullname,
	get_url,
	getdate,
	now,
	today,
	validate_email_address,
)

from central.iam import can, user_has_operator_bypass


class TeamInvitation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		accepted_at: DF.Datetime | None
		accepted_by: DF.Link | None
		email: DF.Data
		expires_on: DF.Date | None
		invited_by: DF.Link | None
		role: DF.Link
		status: DF.Literal["Pending", "Accepted", "Expired", "Revoked"]
		team: DF.Link
	# end: auto-generated types

	expires_in_days: int = 7

	def before_insert(self) -> None:
		self.email = self.email.strip().lower()
		self.status = "Pending"
		self.invited_by = frappe.session.user
		expires_in_days = int(self.expires_in_days or 7)
		if not 1 <= expires_in_days <= 30:
			frappe.throw(_("Invitation expiry must be between 1 and 30 days."))
		self.expires_on = add_days(today(), expires_in_days)
		self.accepted_by = None
		self.accepted_at = None

	def validate(self) -> None:
		validate_email_address(self.email, throw=True)
		if self.is_new():
			self._require_manager()
		self._validate_role()
		self._validate_user()
		self._validate_duplicate()
		self._validate_update()

	def after_insert(self) -> None:
		team_name = frappe.db.get_value("Team", self.team, "team_name")
		invitation_url = get_url(f"/app/team-invitation/{self.name}")
		subject = _("Invitation to join {0}").format(team_name)
		message = frappe.render_template(
			"central/templates/emails/team_invitation.html",
			{
				"team_name": team_name,
				"role": self.role,
				"invited_by": get_fullname(self.invited_by),
				"expires_on": format_date(self.expires_on),
				"invitation_url": invitation_url,
			},
		)

		enqueue_create_notification(
			self.email,
			{
				"subject": subject,
				"type": "Alert",
				"document_type": self.doctype,
				"document_name": self.name,
				"from_user": self.invited_by,
			},
		)

		with suppress(frappe.OutgoingEmailError):
			frappe.sendmail(
				recipients=[self.email],
				subject=subject,
				message=message,
			)

	@frappe.whitelist(methods=["POST"])
	def accept(self) -> dict:
		return self.accept_for_user(frappe.session.user)

	def accept_for_user(self, user: str) -> dict:
		if self.status == "Accepted" and self.accepted_by == user:
			return {"team": self.team, "role": self.role, "accepted": False}
		if self.email != user:
			frappe.throw(_("This invitation belongs to another user."), frappe.PermissionError)
		if self.status != "Pending":
			frappe.throw(_("This invitation is no longer pending."))
		if self._is_expired():
			frappe.throw(_("This invitation has expired."))

		team = frappe.get_doc("Team", self.team)
		team.add_member_from_invitation(user, self.role)

		self.status = "Accepted"
		self.accepted_by = user
		self.accepted_at = now()
		self.flags.from_invitation_action = True
		self.save()
		return {"team": self.team, "role": self.role, "accepted": True}

	@frappe.whitelist(methods=["POST"])
	def revoke(self) -> bool:
		self._require_manager()
		if self.status == "Revoked":
			return False
		if self.status != "Pending":
			frappe.throw(_("Only a pending invitation can be revoked."))
		self.status = "Revoked"
		self.flags.from_invitation_action = True
		self.save()
		return True

	def _validate_role(self) -> None:
		if self.role == "Owner":
			frappe.throw(_("Owner cannot be assigned through an invitation."))
		role_team, is_system = frappe.db.get_value("Team Role", self.role, ["team", "is_system"]) or (None, 0)
		if not is_system and role_team != self.team:
			frappe.throw(_("Team Role {0} does not belong to this team.").format(self.role))

	def _validate_user(self) -> None:
		if not self.is_new():
			return
		enabled = frappe.db.get_value("User", self.email, "enabled")
		if enabled == 0:
			frappe.throw(_("Disabled users cannot be invited."))
		if frappe.db.exists("Team Member", {"parent": self.team, "user": self.email}):
			frappe.throw(_("This user is already a team member."))

	def _validate_duplicate(self) -> None:
		if not self.is_new():
			return
		existing = frappe.db.exists(
			"Team Invitation",
			{"team": self.team, "email": self.email, "status": "Pending"},
		)
		if existing:
			frappe.throw(_("A pending invitation already exists for this user and team."))

	def _validate_update(self) -> None:
		if self.is_new() or self.flags.from_invitation_action or user_has_operator_bypass():
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		fields = ("team", "email", "role", "status", "invited_by", "expires_on", "accepted_by", "accepted_at")
		if any(self.get(field) != previous.get(field) for field in fields):
			frappe.throw(_("Use the invitation actions to change its status."), frappe.PermissionError)

	def _require_manager(self) -> None:
		if not user_has_operator_bypass() and not can(frappe.session.user, self.team, "team:manage_members"):
			frappe.throw(_("Not permitted to manage members for this team."), frappe.PermissionError)

	def _is_expired(self) -> bool:
		return bool(self.expires_on and getdate(self.expires_on) < getdate(today()))


def expire_pending_invitations() -> None:
	for name in frappe.get_all(
		"Team Invitation",
		filters={"status": "Pending", "expires_on": ["<", today()]},
		pluck="name",
	):
		invitation = frappe.get_doc("Team Invitation", name)
		invitation.status = "Expired"
		invitation.save()
