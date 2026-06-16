from __future__ import annotations

import frappe
from frappe.model.document import Document


class AtlasInstance(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data
		api_secret: DF.Password
		base_url: DF.Data
		last_synced_at: DF.Datetime | None
		reachable: DF.Check
		region: DF.Data
		status: DF.Literal["Active", "Draining", "Disabled"]
	# end: auto-generated types

	@frappe.whitelist()
	def test_connection(self) -> dict:
		"""Operator action: ping the Atlas API and record reachability."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw("Not permitted.", frappe.PermissionError)
		from central.atlas_client import AtlasClient

		try:
			AtlasClient(self).ping()
		except Exception as exc:
			self.db_set("reachable", 0)
			return {"reachable": False, "error": str(exc)}
		self.db_set("reachable", 1)
		return {"reachable": True}
