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
		status: DF.Literal["Active", "Suspended"]
		subscription: DF.Link | None
		team: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Team Service"

	def validate(self) -> None:
		if self.status == "Active" and not self.subscription:
			frappe.throw(_("An active service must have a subscription."))

		self.validate_bucket_is_unclaimed()

	def validate_bucket_is_unclaimed(self) -> None:
		"""A readable error ahead of the unique constraint, which is what enforces this.
		Two records over one bucket would each hold a key the other has rotated away."""
		if not self.bucket_name:
			return

		duplicate = frappe.db.exists(
			self._DOCTYPE_NAME,
			{
				"team": self.team,
				"bucket_name": self.bucket_name,
				"name": ("!=", self.name or ""),
			},
		)

		if duplicate:
			frappe.throw(
				_("Team {0} already has a service for bucket {1}.").format(self.team, self.bucket_name)
			)


def on_doctype_update():
	frappe.db.add_unique(
		"Team Service", ["team", "bucket_name"], constraint_name="unique_team_service_bucket"
	)
