# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from central.infrastructure.doctype.region.atlas_connection import AtlasConnectionMixin
from central.infrastructure.doctype.region.cargo_connection import CargoConnectionMixin
from central.integrations.proxy import ProxyClient
from central.integrations.wireguard import WireGuardGatewayClient, WireGuardGatewayError
from central.sso import mint_proxy_token, mint_wireguard_token

REGIONAL_SERVICES = ("proxy", "atlas", "cargo")


class Region(AtlasConnectionMixin, CargoConnectionMixin, Document):
	"""One region: its identity and geography. Its Atlas and Cargo connections are mixed in from
	`atlas_connection.py` and `cargo_connection.py`."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_region_id: DF.Data | None
		automatic_snapshots: DF.Check
		base_url: DF.Data | None
		cargo_base_url: DF.Data | None
		cargo_registered_at: DF.Datetime | None
		cargo_status: DF.Literal["Draft", "Registered", "Disabled"]
		cargo_webhook_secret: DF.Password | None
		connection_checked_at: DF.Datetime | None
		connection_error: DF.SmallText | None
		country_code: DF.Data | None
		display_name: DF.Data | None
		frappemail_service: DF.Link | None
		has_wireguard_gateway: DF.Check
		last_synced_at: DF.Datetime | None
		latitude: DF.Float
		longitude: DF.Float
		provider: DF.Literal[
			"", "AWS", "Hetzner", "Frappe", "OCI", "DigitalOcean", "Scaleway", "Self-Managed", "Fake"
		]
		proxy_domain: DF.Data | None
		reachable: DF.Check
		region: DF.Data
		region_id: DF.Int
		status: DF.Literal["Active", "Draining", "Disabled"]
		telemetry_data_source: DF.Data | None
		webhook_secret: DF.Password | None
	# end: auto-generated types

	def ensure_accepts_new_servers(self) -> None:
		if self.status != "Active":
			frappe.throw(_("This region is not accepting new servers."))

	def validate(self) -> None:
		self.validate_atlas_connection()
		self.validate_cargo_connection()

	def on_update(self) -> None:
		from central.infrastructure.doctype.blocked_domain.blocked_domain import seed_for_zone

		if self.has_value_changed("proxy_domain"):
			seed_for_zone(self.proxy_domain)
		if not self.get_doc_before_save() and frappe.db.get_single_value(
			"Central Settings", "wildcard_domain"
		):
			seed_for_zone(self.get_zone(self.name))

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

	def run_telemetry_sql(self, sql: str) -> tuple[list[str], list[list]]:
		"""Columns and rows of one SQL query on this region's Insights telemetry data source."""
		if not self.telemetry_data_source or "insights" not in frappe.get_installed_apps():
			frappe.throw(_("Region {0} has no telemetry data source.").format(self.name))

		source = frappe.get_doc("Insights Data Source v3", self.telemetry_data_source)
		result = source._get_ibis_backend().raw_sql(sql)
		if hasattr(result, "result_rows"):
			return list(result.column_names), [list(row) for row in result.result_rows]
		return [column[0] for column in result.description], [list(row) for row in result.fetchall()]

	@frappe.whitelist(methods=["POST"])
	def restore_wireguard_devices(self) -> int:
		"""Operator action: rebuild the gateway device table from Central's records."""
		from central.infrastructure.doctype.wireguard_device.wireguard_device import restore_devices

		frappe.only_for("System Manager")
		return restore_devices(self.name)

	@staticmethod
	def get_wireguard_client(region: str) -> WireGuardGatewayClient:
		"""A WireGuard gateway client for one region, with a freshly minted token."""
		doc = frappe.get_cached_doc("Region", region)
		if not doc.has_wireguard_gateway:
			frappe.throw(_("WireGuard VPN is not available in this region yet."), WireGuardGatewayError)

		return WireGuardGatewayClient(
			Region.get_service_url("wireguard", region), mint_wireguard_token(doc.get_atlas_region_id())
		)


def on_doctype_update() -> None:
	frappe.db.add_unique("Region", ["atlas_region_id"])
