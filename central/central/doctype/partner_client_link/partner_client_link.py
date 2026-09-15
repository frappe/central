# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ACTIVE_STATUSES = ("Pending", "Approved")
PARTNER_SUPPORT_ROLE = "Partner Support"


class PartnerClientLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		approved_on: DF.Datetime | None
		buffer: DF.Currency
		client_team: DF.Link
		connect_membership: DF.Data | None
		delinked_on: DF.Datetime | None
		paid_by_partner: DF.Check
		partner_team: DF.Link
		spend_limit: DF.Currency
		status: DF.Literal["Pending", "Approved", "Rejected", "Delinked"]
	# end: auto-generated types

	def validate(self) -> None:
		self._validate_distinct_teams()
		self._validate_partner_team()
		self._validate_client_team_not_a_partner()
		self._validate_single_active_link()

	def _validate_distinct_teams(self) -> None:
		if self.partner_team == self.client_team:
			frappe.throw(_("A team cannot be linked to itself as both partner and client."))

	def _validate_partner_team(self) -> None:
		if not frappe.db.exists("Partner Profile", {"team": self.partner_team}):
			frappe.throw(_("{0} is not a registered partner team.").format(self.partner_team))

	def _validate_client_team_not_a_partner(self) -> None:
		# Mirrors the old same-site rule that a Team can't be both partner and
		# customer — a partner's own Team can't also be someone's client.
		if frappe.db.exists("Partner Profile", {"team": self.client_team}):
			frappe.throw(_("{0} is a partner team and cannot be linked as a client.").format(self.client_team))

	def _validate_single_active_link(self) -> None:
		# Customer to partner is always 1:1 — at most one Pending/Approved link
		# per client team at a time.
		if self.status not in ACTIVE_STATUSES:
			return
		other = frappe.db.exists(
			"Partner Client Link",
			{
				"client_team": self.client_team,
				"status": ["in", ACTIVE_STATUSES],
				"name": ["!=", self.name or ""],
			},
		)
		if other:
			frappe.throw(_("{0} already has an active partner link ({1}).").format(self.client_team, other))

	# Internal; the HTTP surface is central.api.connect.approve_partner_link.
	def approve(self, acting_user: str | None = None) -> None:
		self._require_status("Pending")
		self._require_partner_owner(acting_user)
		self.status = "Approved"
		self.approved_on = frappe.utils.now_datetime()
		self.save(ignore_permissions=True)
		self._grant_partner_support_membership()

	# Internal; the HTTP surface is central.api.connect.reject_partner_link.
	def reject(self, acting_user: str | None = None) -> None:
		self._require_status("Pending")
		self._require_partner_owner(acting_user)
		self.status = "Rejected"
		self.save(ignore_permissions=True)

	# Internal; the HTTP surface is central.api.connect.delink_partner_link.
	def delink(self, acting_user: str | None = None) -> None:
		self._require_status("Approved")
		self._require_partner_or_client_owner(acting_user)
		self.status = "Delinked"
		self.delinked_on = frappe.utils.now_datetime()
		self.save(ignore_permissions=True)
		self._revoke_partner_support_membership()

	def _require_status(self, expected: str) -> None:
		if self.status != expected:
			frappe.throw(_("This action requires the link to be {0}, not {1}.").format(expected, self.status))

	def _require_partner_owner(self, acting_user: str | None) -> None:
		acting_user = acting_user or frappe.session.user
		owner = frappe.db.get_value("Team", self.partner_team, "owner_user")
		if acting_user != owner:
			frappe.throw(_("Only the partner team's owner can do this."), frappe.PermissionError)

	def _require_partner_or_client_owner(self, acting_user: str | None) -> None:
		acting_user = acting_user or frappe.session.user
		owners = frappe.get_all(
			"Team", filters={"name": ["in", [self.partner_team, self.client_team]]}, pluck="owner_user"
		)
		if acting_user not in owners:
			frappe.throw(_("Only the partner or client team's owner can do this."), frappe.PermissionError)

	def _grant_partner_support_membership(self) -> None:
		team = frappe.get_doc("Team", self.client_team)
		partner_owner = frappe.db.get_value("Team", self.partner_team, "owner_user")
		if any(m.user == partner_owner and m.role == PARTNER_SUPPORT_ROLE for m in team.members):
			return
		team.append(
			"members",
			{
				"user": partner_owner,
				"role": PARTNER_SUPPORT_ROLE,
				"resource_type": "*",
				"status": "Active",
			},
		)
		team.flags.from_partner_link_grant = True
		team.save(ignore_permissions=True)

	def _revoke_partner_support_membership(self) -> None:
		team = frappe.get_doc("Team", self.client_team)
		partner_owner = frappe.db.get_value("Team", self.partner_team, "owner_user")
		rows = [m for m in team.members if m.user == partner_owner and m.role == PARTNER_SUPPORT_ROLE]
		if not rows:
			return
		for row in rows:
			team.remove(row)
		team.flags.from_partner_link_grant = True
		team.save(ignore_permissions=True)
