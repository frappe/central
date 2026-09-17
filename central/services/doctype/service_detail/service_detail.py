# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ServiceDetail(Document):
	"""One region's report of one managed service: where it is, and whether it is up."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		activated_on: DF.Datetime | None
		last_updated_on: DF.Datetime | None
		managed_service: DF.Link
		region: DF.Link
		service_endpoint: DF.Data | None
		status: DF.Literal["Available", "Not Available"]
	# end: auto-generated types
