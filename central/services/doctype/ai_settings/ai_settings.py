# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from central.integrations.grove import GroveClient


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

	def set_credential(self, credential: dict) -> None:
		self.control_api_key = credential["api_key"]
		self.control_api_secret = credential["api_secret"]
		self.save()


# Plain whitelisted calls, not doc methods: a form's doc method gets its arguments nested
# under `args`, where a secret cannot be popped from the request before it is logged.


@frappe.whitelist(methods=["POST"])
def enroll() -> None:
	"""Desk button: exchange the bootstrap secret Grove was given for Central's own control
	credential. The secret is popped from the raw request, so it is never logged."""
	frappe.only_for("System Manager")
	secret = frappe.local.form_dict.pop("bootstrap_secret", None)
	if not secret:
		frappe.throw(_("Bootstrap secret is required."))

	settings = frappe.get_single("AI Settings")
	if not settings.base_url:
		frappe.throw(_("Set the Grove URL first."))

	settings.set_credential(GroveClient.enroll(settings.base_url, secret))


@frappe.whitelist(methods=["POST"])
def rotate_credential() -> None:
	"""Desk button: a new control secret from Grove. The old one stops at once."""
	frappe.only_for("System Manager")
	frappe.get_single("AI Settings").set_credential(GroveClient.from_settings().rotate_control_key())
