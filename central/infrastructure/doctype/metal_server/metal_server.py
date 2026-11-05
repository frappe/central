# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from typing import Literal

import frappe
from frappe import _
from frappe.model.document import Document

from central.integrations.atlas import AtlasClient


class MetalServer(Document):
	"""A bare metal server and how to reach it."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.infrastructure.doctype.metal_server_incident.metal_server_incident import (
			MetalServerIncident,
		)

		atlas_host_id: DF.Data | None
		bmc_password: DF.Password | None
		bmc_url: DF.Data | None
		bmc_username: DF.Password | None
		cost_per_month_inr: DF.Currency
		cpu_overcommit_ratio: DF.Float
		deployed_on: DF.Date | None
		disk_gib: DF.Int
		incidents: DF.Table[MetalServerIncident]
		memory_gib: DF.Int
		model: DF.Data | None
		os: DF.Data | None
		ownership: DF.Literal["Rented", "Owned"]
		private_ipv4: DF.Data | None
		public_ipv4: DF.Data | None
		purchase_price_inr: DF.Currency
		purchased_on: DF.Date | None
		region: DF.Link
		reserved_disk_gib: DF.Int
		reserved_memory_gib: DF.Int
		reserved_vcpus: DF.Int
		root_password: DF.Password | None
		root_username: DF.Password | None
		status: DF.Literal["Active", "Archived"]
		vcpus: DF.Int
		vendor: DF.Data
		warranty_until: DF.Date | None
	# end: auto-generated types

	def validate(self) -> None:
		# A mandatory number still accepts 0, and a free or coreless machine breaks the margin reports.
		for fieldname in ("cost_per_month_inr", "vcpus"):
			if self.get(fieldname) <= 0:
				frappe.throw(_("{0} must be more than 0.").format(_(self.meta.get_label(fieldname))))

		for reserved, physical in (
			("reserved_vcpus", "vcpus"),
			("reserved_memory_gib", "memory_gib"),
			("reserved_disk_gib", "disk_gib"),
		):
			if self.get(reserved) and self.get(reserved) >= (self.get(physical) or 0):
				frappe.throw(
					_("{0} must be less than {1}.").format(
						_(self.meta.get_label(reserved)), _(self.meta.get_label(physical))
					)
				)

	@frappe.whitelist(methods=["POST"])
	def link_atlas_host(self) -> str:
		"""Record the region's Atlas host whose title is this machine's name."""
		frappe.only_for("System Manager")
		region = frappe.get_doc("Region", self.region)
		self.db_set("atlas_host_id", AtlasClient.for_operator(region).get_host_id(self.name))
		return self.atlas_host_id

	@frappe.whitelist(methods=["POST"])
	def get_credentials(self, kind: Literal["root", "bmc"]) -> dict[str, str | None]:
		"""Return the root or BMC login to a system user with System Manager."""
		frappe.only_for("System Manager")

		return {
			"username": self.get_password(f"{kind}_username", raise_exception=False),
			"password": self.get_password(f"{kind}_password", raise_exception=False),
		}
