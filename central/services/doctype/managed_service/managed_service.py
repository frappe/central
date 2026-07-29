# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ManagedService(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		add_on_service: DF.Link
		provider_ref: DF.Data | None
		status: DF.Literal["Draft", "Provisioning", "Active", "Failed", "Suspended"]
		subscription: DF.Link
		team: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Managed Service"

	# A team activates a given add-on at most once. The DB carries the race-safe
	# composite unique index; this only gives a readable error first.
	def validate(self) -> None:
		duplicate = frappe.db.exists(
			self._DOCTYPE_NAME,
			{"team": self.team, "add_on_service": self.add_on_service, "name": ("!=", self.name or "")},
		)

		if duplicate:
			frappe.throw(_("Team {0} already has the {1} service.").format(self.team, self.add_on_service))


def on_doctype_update():
	# Race-safe arbiter for the one-add-on-per-team invariant; runs on migrate.
	frappe.db.add_unique("Managed Service", ["team", "add_on_service"], constraint_name="unique_team_add_on")
