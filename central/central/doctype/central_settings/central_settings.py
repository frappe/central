# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
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
	# end: auto-generated types

	@classmethod
	def feature_flags(cls) -> dict[str, bool]:
		"""The console's feature flags as a plain {name: bool} map for window boot.
		Cached — this is read on every dashboard page load."""
		settings = frappe.get_cached_doc("Central Settings")
		return {"addons": bool(settings.enable_addons)}
