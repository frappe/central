from __future__ import annotations

from frappe.model.document import Document


class Asset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cluster: DF.Link
		gateway_url: DF.Data | None
		last_synced_at: DF.Datetime | None
		resource_id: DF.Data
		status: DF.Literal["Provisioning", "Running", "Stopped", "Terminated"]
		team: DF.Link
	# end: auto-generated types

	pass
