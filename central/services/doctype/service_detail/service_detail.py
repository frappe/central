# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.database import savepoint
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
	def endpoint_for(region: str, service: str) -> str | None:
		"""Where one region serves one service, or None while it does not.

		A region that has never reported has no row, and one reporting `Not Available` has
		an endpoint that would refuse the caller, so both read as nothing to hand out."""
		detail = frappe.db.get_value(
			"Service Detail",
			f"{region}-{service}",
			["status", "service_endpoint"],
			as_dict=True,
			cache=True,
		)
		if not detail or detail.status != "Available":
			return None

		return detail.service_endpoint or None

	@staticmethod
	def record_report(region: str, service: str, status: str, service_endpoint: str | None) -> str:
		"""Record what a region reports about one of its services. `activated_on` marks the
		first report of an outage ending, not every report."""
		detail = ServiceDetail._locked_row(region, service)

		became_available = status == "Available" and detail.status != "Available"
		detail.status = status
		detail.service_endpoint = service_endpoint
		detail.last_updated_on = frappe.utils.now_datetime()
		if became_available:
			detail.activated_on = detail.last_updated_on

		# A region reports as a guest; the delivery's signature is what authorises this write.
		detail.save(ignore_permissions=True)
		return detail.name

	@staticmethod
	def _locked_row(region: str, service: str) -> "ServiceDetail":
		"""This region's row for one service, locked for the rest of the request. Two
		deliveries can both find no row; the name is the primary key, so the losing insert
		is refused and reads the winner's row instead of failing the delivery."""
		name = f"{region}-{service}"
		if not frappe.db.exists("Service Detail", name):
			inserted = None
			with savepoint(catch=frappe.DuplicateEntryError):
				inserted = (
					frappe.new_doc("Service Detail")
					.update({"region": region, "service": service})
					.insert(ignore_permissions=True)
				)
			if inserted:
				return inserted

		return frappe.get_doc("Service Detail", name, for_update=True)
