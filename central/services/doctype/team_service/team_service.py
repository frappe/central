# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TeamService(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_key: DF.Data | None
		add_on_service: DF.Link
		bucket_name: DF.Data | None
		endpoint_url: DF.Data | None
		region: DF.Link
		secret_access_key: DF.Password | None
		status: DF.Literal["Draft", "Provisioning", "Active", "Failed", "Suspended"]
		subscription: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Team Service"

	def validate(self) -> None:
		if self.status == "Active" and not self.subscription:
			frappe.throw(_("An active service must have a subscription."))

		duplicate = frappe.db.exists(
			self._DOCTYPE_NAME,
			{
				"team": self.team,
				"add_on_service": self.add_on_service,
				"region": self.region,
				"name": ("!=", self.name or ""),
			},
		)

		if duplicate:
			frappe.throw(
				_("Team {0} already has the {1} service in {2}.").format(
					self.team, self.add_on_service, self.region
				)
			)


def on_doctype_update():
	frappe.db.add_unique(
		"Team Service",
		["team", "add_on_service", "region"],
		constraint_name="unique_team_add_on_in_region",
	)
