# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ServiceBackend(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		base_url: DF.Data
		control_api_key: DF.Data
		control_api_secret: DF.Password
		is_active: DF.Check
		region: DF.Data | None
		service: DF.Link
	# end: auto-generated types

	_DOCTYPE_NAME = "Service Backend"

	def validate(self) -> None:
		# region is the second half of the (service, region) identity; store "" not
		# NULL so re-register lookups match and the unique index (on_doctype_update)
		# can arbitrate. NULL <> "" in MariaDB, which is what duplicated rows.
		self.region = self.region or ""

	@frappe.whitelist()
	def enroll(self) -> None:
		"""Desk entry point. The one-time bootstrap secret is read from the raw request
		and popped, so it is never recorded as a logged whitelist argument."""
		self.apply_control_credential(pop_bootstrap_secret())

	def apply_control_credential(self, bootstrap_secret: str) -> None:
		"""Exchange a bootstrap secret for this backend's own control credential, minted
		by the executor. Stores it write-only and activates."""
		from central.services.drivers.base import get_driver

		handler = frappe.db.get_value("Add-on Service", self.service, "handler_key")
		credentials = get_driver(handler).enroll(self.base_url, bootstrap_secret)

		self.control_api_key = credentials["api_key"]
		self.control_api_secret = credentials["api_secret"]
		self.is_active = 1

		self.save()


def on_doctype_update():
	# One backend per (service, region); region normalised to "" in validate so the
	# unique index arbitrates re-registration instead of duplicating rows.
	frappe.db.add_unique("Service Backend", ["service", "region"], constraint_name="unique_service_region")


def pop_bootstrap_secret() -> str:
	"""Read and remove the bootstrap secret from the raw request so Frappe never
	persists it as a whitelisted argument in the Request/Error log."""
	secret = frappe.local.form_dict.pop("bootstrap_secret", None)
	if not secret:
		frappe.throw(frappe._("Bootstrap secret is required."))

	return secret
