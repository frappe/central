from __future__ import annotations

from urllib.parse import urlparse

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
		peer_endpoint: DF.Data | None
		peer_public_key: DF.SmallText | None
		reachable: DF.Check
		region: DF.Data
		service_user: DF.Link | None
		skip_tunnel: DF.Check
		status: DF.Literal["Active", "Draining", "Disabled"]
		tunnel_ip: DF.Data | None
		tunnel_status: DF.Literal["Unregistered", "Provisioning", "Active", "Inactive"]
		tunnel_url: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		"""Keep `tunnel_url` derived from `tunnel_ip` (the post-registration data path).
		Computed here so it can never drift from the allocated address."""
		self.tunnel_url = self._derive_tunnel_url()

	def _derive_tunnel_url(self) -> str | None:
		"""The data path over wg0, mirroring base_url's scheme + port so it matches how
		this Atlas is actually served. The WireGuard tunnel already encrypts the hop, so
		we do NOT assume TLS on the tunnel IP — http base_url -> http tunnel_url. e.g.
		base_url http://1.2.3.4:8000 -> http://10.88.0.2:8000; https://host -> https://10.88.0.2."""
		if not self.tunnel_ip:
			return None
		parsed = urlparse(self.base_url or "")
		scheme = parsed.scheme or "https"
		port = f":{parsed.port}" if parsed.port else ""
		return f"{scheme}://{self.tunnel_ip}{port}"

	@frappe.whitelist()
	def register(self) -> dict:
		"""Operator action: run the full Central-driven tunnel registration handshake
		(central/spec/TUNNEL.md § Register Atlas) — ping, allocate, provision, peer,
		verify over the tunnel, confirm. The orchestration lives in the integration
		module; this is the thin doctype entry point the form button calls."""
		from central.integrations.atlas import register_atlas

		return register_atlas(self)

	@frappe.whitelist()
	def remove_tunnel(self) -> dict:
		"""Operator action: strip the tunnel + management firewall but keep the Atlas
		registered — revert the firewall + drop wg0 on the Atlas and remove the hub peer,
		while retaining the service user and the allocated tunnel_ip. Status
		goes to Inactive; Register brings the tunnel back up."""
		from central.integrations.atlas import remove_tunnel

		return remove_tunnel(self)

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
