# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

# Mirrors atlas.atlas.core.mesh_address: the region owns bits 96-111 of every mesh
# address, and Atlas derives both audiences from the same number.
MESH_PREFIX = 0xFDAA
MAXIMUM_REGION_ID = 0xFFFF
ADMIN_AUDIENCE_PREFIX = "atlas-admin"
PROXY_AUDIENCE_PREFIX = "atlas-proxy"


class Region(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_base_url: DF.Data | None
		country_code: DF.Data | None
		display_name: DF.Data | None
		latitude: DF.Float
		longitude: DF.Float
		mesh_address_prefix: DF.Data | None
		provider: DF.Literal[
			"", "AWS", "Hetzner", "Frappe", "OCI", "DigitalOcean", "Scaleway", "Self-Managed", "Fake"
		]
		proxy_control_url: DF.Data | None
		region: DF.Data
		region_id: DF.LongInt | None
		status: DF.Literal["Active", "Draining", "Disabled"]
		wildcard_domain: DF.Data | None
	# end: auto-generated types

	_DOCTYPE_NAME = "Region"

	def validate(self) -> None:
		"""A region carries no number until an operator reads it off that region's own
		Atlas Settings, so an unset one is allowed here and refused at minting."""
		if self.region_id is None:
			self.mesh_address_prefix = None
			return

		self._validate_region_id()
		self.mesh_address_prefix = f"{MESH_PREFIX:x}:{self.region_id:x}"

	@classmethod
	def admin_audience(cls, region: str) -> str:
		"""The audience a token for this region's Atlas API must carry."""
		return f"{ADMIN_AUDIENCE_PREFIX}:{cls.region_id_of(region)}"

	@classmethod
	def proxy_audience(cls, region: str) -> str:
		"""The audience a token for this region's proxy control API must carry."""
		return f"{PROXY_AUDIENCE_PREFIX}:{cls.region_id_of(region)}"

	@classmethod
	def region_id_of(cls, region: str) -> int:
		"""The region number, refusing a region that has none rather than signing a
		token no region would accept."""
		region_id = frappe.db.get_value(cls._DOCTYPE_NAME, region, "region_id")
		if region_id is None:
			frappe.throw(_("Region {0} has no region ID.").format(region), frappe.ValidationError)
		return region_id

	def _validate_region_id(self) -> None:
		"""Atlas reads these 16 bits out of the mesh address, so a region outside the
		range would address another region's machines."""
		if not 0 <= self.region_id <= MAXIMUM_REGION_ID:
			frappe.throw(_("Region ID must be between 0 and {0}.").format(MAXIMUM_REGION_ID))
