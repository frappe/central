# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceCredential(Document):
	"""A provider credential Central issued under a team's Managed Service. `subject_type`
	discriminates the shapes that share the same billing meter: a per-`Site` credential the
	bench delivers to one site, a team-level API key (`Team`) with a `label` for use in the
	customer's own apps, or a per-`Bench` object-storage key scoped to that bench's bucket.
	Each is revocable on its own."""

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
		pilot_credential: DF.Link | None
		provider_ref: DF.Data | None
		site: DF.Link | None
		status: DF.Literal["Active", "Revoked", "Failed"]
		subject_type: DF.Literal["Site", "Team", "Bench"]
	# end: auto-generated types

	def validate(self) -> None:
		if self.subject_type == "Site":
			self._validate_site_subject()
		elif self.subject_type == "Team" and not self.label:
			frappe.throw(_("A team API key needs a label."))
		elif self.subject_type == "Bench" and not self.pilot_credential:
			frappe.throw(_("A bench credential needs a pilot credential."))

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
	# The same arbiter for bench credentials. Site and team rows carry a NULL pilot
	# credential, so they never collide on this index.
	frappe.db.add_unique(
		"Service Credential",
		["managed_service", "pilot_credential"],
		constraint_name="unique_managed_service_bench",
	)
