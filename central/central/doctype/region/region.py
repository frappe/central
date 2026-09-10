# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Atlas packs the region id into the second 16-bit group of every mesh address.
MAXIMUM_ATLAS_REGION_ID = 0xFFFF


class Region(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_region_id: DF.Int
		country_code: DF.Data | None
		display_name: DF.Data | None
		latitude: DF.Float
		longitude: DF.Float
		provider: DF.Literal[
			"", "AWS", "Hetzner", "Frappe", "OCI", "DigitalOcean", "Scaleway", "Self-Managed", "Fake"
		]
		region: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "Region"

	def before_insert(self) -> None:
		"""Number the region so nothing has to pass one in. Atlas is the authority: correct
		this to its own region id before a Cargo host enrols here."""
		if self.atlas_region_id:
			return

		highest = frappe.get_all("Region", pluck="atlas_region_id", order_by="atlas_region_id desc", limit=1)
		self.atlas_region_id = (highest[0] if highest else 0) + 1

	def validate(self) -> None:
		"""A region Atlas could not address is not one Cargo can be pointed at."""
		if not 1 <= self.atlas_region_id <= MAXIMUM_ATLAS_REGION_ID:
			frappe.throw(_("Atlas Region ID must be between 1 and {0}.").format(MAXIMUM_ATLAS_REGION_ID))
