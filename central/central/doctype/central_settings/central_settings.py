# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document


class CentralSettings(Document):
	"""Console feature flags, one Check each, read at page boot so the console can hide an area."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		central_id: DF.Int
		common_site_config: DF.JSON | None
		enable_addons: DF.Check
		enable_email_delivery_service: DF.Check
		enable_llm_service: DF.Check
		enable_object_storage_service: DF.Check
		enable_pdf_print_service: DF.Check
		invitation_expiry_days: DF.Int
		invitation_resend_cooldown_minutes: DF.Int
		invitations_per_hour: DF.Int
		sign_in_code_attempts: DF.Int
		sign_in_codes_per_email: DF.Int
		trial_idle_shutdown_minutes: DF.Int
		trial_servers_per_team: DF.Int
		wildcard_domain: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		self.validate_limits()
		self.validate_common_site_config()

	def validate_limits(self) -> None:
		"""A zero would refuse every invitation, every sign-in code, or every wrong code at once."""
		for fieldname in ("invitations_per_hour", "sign_in_code_attempts", "sign_in_codes_per_email"):
			if self.get(fieldname) < 1:
				frappe.throw(_("{0} must be at least 1.").format(_(self.meta.get_label(fieldname))))

	def validate_common_site_config(self) -> None:
		from central.integrations.atlas import MAXIMUM_METADATA_BYTES

		try:
			config = self.get_common_site_config()
		except ValueError:
			config = None
		if not isinstance(config, dict):
			frappe.throw(_('Common Site Config must be a JSON object, such as {"key": "value"}.'))
		if len(json.dumps(config).encode()) > MAXIMUM_METADATA_BYTES:
			frappe.throw(_("Common Site Config must fit in {0} bytes.").format(MAXIMUM_METADATA_BYTES))

	def get_common_site_config(self) -> dict:
		return frappe.parse_json(self.common_site_config or "{}")

	def feature_flags(self) -> dict[str, bool]:
		"""The console's feature flags as a plain {name: bool} map for window boot.
		`addons` gates the whole area; the rest are per-service rollout switches the
		Add-ons page reads to decide which cards are live vs "coming soon"."""
		return {
			"addons": bool(self.enable_addons),
			"llm": bool(self.enable_llm_service),
			"pdf": bool(self.enable_pdf_print_service),
			"email": bool(self.enable_email_delivery_service),
			"storage": bool(self.enable_object_storage_service),
		}
