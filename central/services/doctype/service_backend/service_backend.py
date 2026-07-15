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

	@frappe.whitelist()
	def enroll(self, bootstrap_secret: str) -> None:
		"""Exchange a one-time bootstrap secret for this backend's own control
		credential, minted by the executor. Stores it write-only and activates."""
		from central.services.drivers.base import get_driver

		handler = frappe.db.get_value("Add-on Service", self.service, "handler_key")
		credentials = get_driver(handler).enroll(self.base_url, bootstrap_secret)

		self.control_api_key = credentials["api_key"]
		self.control_api_secret = credentials["api_secret"]
		self.is_active = 1

		self.save()
