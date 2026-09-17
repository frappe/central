# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
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
		region: DF.Link
		service: DF.Literal["telemetry", "storage"]
		service_endpoint: DF.Data | None
		status: DF.Literal["Available", "Not Available"]
	# end: auto-generated types

	@staticmethod
	def record_report(region: str, service: str, status: str, service_endpoint: str | None) -> str:
		"""Record what a region reports about one of its services, and return the row.

		The row is named for the pair it describes, so a region reporting again writes the
		same row rather than a second one. `activated_on` is the first moment the service
		was reported available and stays put until it goes away again."""
		name = f"{region}-{service}"
		detail = (
			frappe.get_doc("Service Detail", name)
			if frappe.db.exists("Service Detail", name)
			else frappe.new_doc("Service Detail").update({"region": region, "service": service})
		)

		became_available = status == "Available" and detail.status != "Available"
		detail.status = status
		detail.service_endpoint = service_endpoint
		detail.last_updated_on = frappe.utils.now_datetime()
		if became_available:
			detail.activated_on = detail.last_updated_on

		# A region reports as a guest; the delivery's signature is what authorises this write.
		detail.save(ignore_permissions=True)
		return detail.name
