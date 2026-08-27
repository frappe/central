# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceCredential(Document):
	"""A provider credential Central issued under a team's Managed Service. `subject_type`
	discriminates the two shapes that share the same billing meter: a per-`Site` credential
	the bench delivers to one site, or a team-level credential (`Team`) with a `label` — an
	API key for the customer's own apps, or an object-storage bucket and its key. Each is
	revocable on its own."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		gateway_url: DF.Data | None
		label: DF.Data | None
		last_usage_total: DF.Float
		managed_service: DF.Link
		provider_bucket_id: DF.Data | None
		provider_ref: DF.Data | None
		service_backend: DF.Link | None
		site: DF.Link | None
		status: DF.Literal["Active", "Revoked", "Failed"]
		subject_type: DF.Literal["Site", "Team"]
	# end: auto-generated types

	def validate(self) -> None:
		if self.subject_type == "Site":
			self._validate_site_subject()
		elif self.subject_type == "Team" and not self.label:
			frappe.throw(_("A team API key needs a label."))

	def _validate_site_subject(self) -> None:
		if not self.site:
			frappe.throw(_("A site credential needs a site."))

		# One credential per (managed service, target site). The DB composite unique
		# index is the race-safe arbiter; this only gives a readable error first.
		duplicate = frappe.db.exists(
			"Service Credential",
			{
				"subject_type": "Site",
				"managed_service": self.managed_service,
				"site": self.site,
				"name": ("!=", self.name or ""),
			},
		)
		if duplicate:
			frappe.throw(_("A credential for site {0} already exists on this service.").format(self.site))


def on_doctype_update():
	# Race-safe arbiter for one-credential-per-site; runs on migrate. Team keys carry a
	# NULL site, which a unique index treats as distinct, so they never collide here.
	frappe.db.add_unique(
		"Service Credential", ["managed_service", "site"], constraint_name="unique_managed_service_site"
	)
