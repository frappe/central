# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Central is a Passport client like any site, and also the operator that registers the
# sites it provisions. Both need the same two things: where Passport lives, and an
# operator credential holding the Passport Manager role.


class CentralPassportSettings(Document):
	def validate(self):
		from frappe.integrations.openid_connect.urls import origin, validate_endpoint

		if not self.enabled:
			return

		if not self.issuer or not self.api_key or not self.api_secret:
			frappe.throw(_("Frappe sign-in needs an issuer URL and operator credentials."))

		try:
			validate_endpoint(self.issuer.rstrip("/"), allow_local_http=bool(self.allow_local_http))
		except ValueError as error:
			frappe.throw(str(error))

		if origin(self.issuer) != self.issuer.rstrip("/"):
			frappe.throw(_("The issuer must be a bare origin, with no path."))

	@classmethod
	def active(cls) -> "CentralPassportSettings | None":
		"""The settings, or None when Frappe sign-in is switched off for this deployment."""
		settings = frappe.get_cached_doc("Central Passport Settings")

		return settings if settings.enabled and settings.issuer else None
