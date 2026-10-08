# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

# Central's console feature flags. One Single, one Check per flag, read at page
# boot (get_context) so the SPA can hide a whole area before its routes mount.


class CentralSettings(Document):
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
		trial_idle_shutdown_minutes: DF.Int
		wildcard_domain: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		from central.infrastructure.doctype.user_mail_account.user_mail_account import MAILBOX_CONFIG_BYTES
		from central.integrations.atlas import MAXIMUM_METADATA_VALUE_BYTES

		try:
			config = self.get_common_site_config()
		except ValueError:
			config = None
		if not isinstance(config, dict):
			frappe.throw(_('Common Site Config must be a JSON object, such as {"key": "value"}.'))
		# A server's mailbox keys travel in the same metadata value.
		limit = MAXIMUM_METADATA_VALUE_BYTES - MAILBOX_CONFIG_BYTES
		if len(json.dumps(config).encode()) > limit:
			frappe.throw(_("Common Site Config must fit in {0} bytes.").format(limit))

	def get_common_site_config(self) -> dict:
		return json.loads(self.common_site_config or "{}")

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
