# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SiteServiceCredential(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		gateway_url: DF.Data | None
		last_usage_total: DF.Float
		managed_service: DF.Link
		provider_ref: DF.Data | None
		site: DF.Link | None
		status: DF.Literal["Active", "Revoked", "Failed"]
	# end: auto-generated types

	_DOCTYPE_NAME = "Site Service Credential"

	# One credential per (managed service, target site). The DB composite unique
	# index is the race-safe arbiter; this only gives a readable error first.
	def validate(self) -> None:
		duplicate = frappe.db.exists(
			self._DOCTYPE_NAME,
			{"managed_service": self.managed_service, "site": self.site, "name": ("!=", self.name or "")},
		)

		if duplicate:
			frappe.throw(_("A credential for site {0} already exists on this service.").format(self.site))


def on_doctype_update():
	# Race-safe arbiter for one-credential-per-site; runs on migrate.
	frappe.db.add_unique(
		"Site Service Credential", ["managed_service", "site"], constraint_name="unique_managed_service_site"
	)
