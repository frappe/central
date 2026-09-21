# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.central.doctype.region.atlas_connection import AtlasConnectionMixin
from central.integrations.proxy import ProxyClient
from central.sso import mint_proxy_token

REGIONAL_SERVICES = ("proxy", "atlas", "cargo")


class Region(AtlasConnectionMixin, Document):
	"""One region. Its own identity and geography live here; its connection to Atlas is
	mixed in from `atlas_connection.py`."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_region_id: DF.Data | None
		base_url: DF.Data
		connection_checked_at: DF.Datetime | None
		connection_error: DF.SmallText | None
		country_code: DF.Data | None
		display_name: DF.Data | None
		last_synced_at: DF.Datetime | None
		latitude: DF.Float
		longitude: DF.Float
		proxy_domain: DF.Data | None
		provider: DF.Literal[
			"", "AWS", "Hetzner", "Frappe", "OCI", "DigitalOcean", "Scaleway", "Self-Managed", "Fake"
		]
		reachable: DF.Check
		region: DF.Data
		status: DF.Literal["Active", "Draining", "Disabled"]
		webhook_secret: DF.Password | None
	# end: auto-generated types

	_DOCTYPE_NAME = "Region"

	def validate(self) -> None:
		self.validate_atlas_connection()

	@staticmethod
	def get_zone(region: str) -> str:
		"""The DNS zone of one region: `<region>.<wildcard domain>`."""
		wildcard_domain = frappe.db.get_single_value("Central Settings", "wildcard_domain")
		if not wildcard_domain:
			frappe.throw(_("Set the Wildcard Domain in Central Settings."))
		return f"{region}.{wildcard_domain.strip().strip('.').lower()}"

	@staticmethod
	def get_service_url(service: str, region: str) -> str:
		"""The base URL of a regional service, such as `https://proxy.<region>.<wildcard domain>`."""
		return f"https://{service}.{Region.get_zone(region)}"

	@staticmethod
	def get_proxy_client(region: str) -> ProxyClient:
		"""A proxy client for one region, with a freshly minted token."""
		region_id = frappe.get_doc("Region", region).get_atlas_region_id()
		return ProxyClient(Region.get_service_url("proxy", region), mint_proxy_token(region_id))


def on_doctype_update() -> None:
	frappe.db.add_unique("Region", ["atlas_region_id"])
