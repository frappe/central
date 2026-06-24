from __future__ import annotations

import frappe
from frappe.model.document import Document


class AtlasInstance(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		admin_api_key: DF.Data | None
		admin_api_secret: DF.Password | None
		api_key: DF.Data
		api_secret: DF.Password
		atlas_id: DF.Data | None
		base_url: DF.Data
		last_synced_at: DF.Datetime | None
		peer_endpoint: DF.Data | None
		peer_public_key: DF.SmallText | None
		region: DF.Data
		service_user: DF.Link | None
		status: DF.Literal["Active", "Draining", "Disabled"]
		tunnel_ip: DF.Data | None
		tunnel_status: DF.Literal["Unregistered", "Provisioning", "Active"]
		tunnel_url: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		"""Keep `tunnel_url` derived from `tunnel_ip` (the post-registration data path,
		e.g. https://10.88.0.2). Computed here so it can never drift from the allocated
		address."""
		self.tunnel_url = f"https://{self.tunnel_ip}" if self.tunnel_ip else None

	@frappe.whitelist()
	def register(self) -> dict:
		"""Operator action: run the full Central-driven tunnel registration handshake
		(central/spec/TUNNEL.md § Register Atlas) — ping, allocate, provision, peer,
		verify over the tunnel, confirm. The orchestration lives in the integration
		module; this is the thin doctype entry point the form button calls."""
		from central.integrations.atlas import register_atlas

		return register_atlas(self)

	@frappe.whitelist()
	def test_connection(self) -> dict:
		"""Operator action: ping the Atlas API and record reachability."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw("Not permitted.", frappe.PermissionError)
		from central.integrations.atlas import AtlasClient

		try:
			AtlasClient(self).ping()
		except Exception as exc:
			self.db_set("reachable", 0)
			return {"reachable": False, "error": str(exc)}
		self.db_set("reachable", 1)
		return {"reachable": True}
