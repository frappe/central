from __future__ import annotations

from frappe.model.document import Document


class Asset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cluster: DF.Link
		disk_gigabytes: DF.Int
		gateway_url: DF.Data | None
		ipv6_address: DF.Data | None
		last_event_at: DF.Datetime | None
		last_synced_at: DF.Datetime | None
		memory_megabytes: DF.Int
		public_ipv4: DF.Data | None
		resource_id: DF.Data
		status: DF.Literal["Pending", "Running", "Paused", "Stopped", "Failed", "Terminated"]
		team: DF.Link
		title: DF.Data | None
		vcpus: DF.Int
	# end: auto-generated types

	pass
