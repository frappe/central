# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ACTIVE_STATUSES = ("Pending", "Approved")


class PartnerClientLink(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		buffer: DF.Currency
		client_team: DF.Link
		connect_membership: DF.Data
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
