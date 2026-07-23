# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ServiceAPIKey(Document):
	"""A team-level inference API key Central issued from the provider (Grove), for use
	in the customer's own apps. Same billing meter as site keys; revocable on its own."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		gateway_url: DF.Data | None
		label: DF.Data
		last_usage_total: DF.Float
		managed_service: DF.Link
		provider_ref: DF.Data | None
		status: DF.Literal["Active", "Revoked", "Failed"]
	# end: auto-generated types

	pass
