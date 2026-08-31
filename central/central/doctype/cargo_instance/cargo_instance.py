from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class CargoInstance(Document):
	"""One Cargo host, and the region it provisions for.

	Simpler than an Atlas Instance: Cargo is a plain Frappe site reachable over the
	network, so there is no tunnel to allocate and no peering to arrange."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data
		api_secret: DF.Password
		atlas_access_token: DF.Password | None
		base_url: DF.Data
		central_access_token: DF.Password | None
		last_synced_at: DF.Datetime | None
		reachable: DF.Check
		region: DF.Link
		status: DF.Literal["Draft", "Registered", "Disabled"]
	# end: auto-generated types

	@frappe.whitelist()
	def register(self) -> dict:
		"""Operator action: mint this host's token and push it, with the upstream URLs,
		into its Cargo Settings."""
		from central.integrations.cargo import register_cargo

		return register_cargo(self)

	@frappe.whitelist()
	def test_connection(self) -> dict:
		"""Operator action: ask the host whether it is alive and configured."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		from central.integrations.cargo import cargo_status

		try:
			status = cargo_status(self)
		except Exception as exception:
			self.record_reach(reachable=False)
			return {"reachable": False, "error": str(exception)}

		self.record_reach(reachable=status.get("configured", False))

		return {"reachable": True, **status}

	def record_reach(self, reachable: bool) -> None:
		"""Note whether the host answered, and when."""
		self.reachable = int(reachable)
		if reachable:
			self.last_synced_at = frappe.utils.now_datetime()
		self.save(ignore_permissions=True)
