# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

from frappe.model.document import Document

# Central's console feature flags. One Single, one Check per flag, read at page
# boot (get_context) so the SPA can hide a whole area before its routes mount.


class CentralSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enable_addons: DF.Check
		enable_email_delivery_service: DF.Check
		enable_llm_service: DF.Check
		enable_object_storage_service: DF.Check
		enable_pdf_print_service: DF.Check
		host_task_retention_days: DF.Int
	# end: auto-generated types

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
