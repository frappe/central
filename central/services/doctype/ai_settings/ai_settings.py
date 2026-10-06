# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AISettings(Document):
	"""Where Grove is and the control credential Central calls it with."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		base_url: DF.Data | None
		control_api_key: DF.Data | None
		control_api_secret: DF.Password | None
	# end: auto-generated types

	def validate(self) -> None:
		self.base_url = (self.base_url or "").strip().rstrip("/")

	@frappe.whitelist()
	def enroll(self) -> None:
		"""Exchange a bootstrap secret for Central's own control credential at Grove. The secret
		is popped from the raw request, so it is never logged as a whitelisted argument."""
		from central.integrations.grove import GroveClient

		frappe.only_for("System Manager")
		secret = frappe.local.form_dict.pop("bootstrap_secret", None)
		if not secret:
			frappe.throw(_("Bootstrap secret is required."))
		if not self.base_url:
			frappe.throw(_("Set the Grove URL first."))

		credentials = GroveClient.enroll(self.base_url, secret)
		self.control_api_key = credentials["api_key"]
		self.control_api_secret = credentials["api_secret"]
		self.save()
