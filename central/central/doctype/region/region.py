# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class Region(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		country_code: DF.Data | None
		display_name: DF.Data | None
		latitude: DF.Float
		longitude: DF.Float
		provider: DF.Literal["", "AWS", "Hetzner", "Frappe", "OCI", "DigitalOcean", "Scaleway", "Self-Managed", "Fake"]
		region: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "Region"
