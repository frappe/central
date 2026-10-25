from __future__ import annotations

import base64
import binascii

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max

from central.identity.doctype.team.tenant import validate_tenant_id
from central.infrastructure.doctype.region.region import Region
from central.integrations.wireguard import WireGuardGatewayClient, WireGuardGatewayError

MAXIMUM_CLIENT_ID = 65535


class WireGuardDevice(Document):
	"""A customer device that reaches the team's servers in one region through its WireGuard gateway."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		added_by: DF.Link | None
		address: DF.Data | None
		allowed_ips: DF.SmallText | None
		client_id: DF.Int
		endpoint: DF.Data | None
		gateway_public_key: DF.Data | None
		last_error: DF.SmallText | None
		public_key: DF.Data
		region: DF.Link
		status: DF.Literal["Active", "Removing"]
		team: DF.Link
		title: DF.Data
	# end: auto-generated types

	def before_validate(self) -> None:
		self.public_key = (self.public_key or "").strip()

	def validate(self) -> None:
		try:
			is_key = len(base64.b64decode(self.public_key, validate=True)) == 32
		except binascii.Error:
			is_key = False
		if not is_key:
			frappe.throw(_("Enter a WireGuard public key. It has 44 characters and ends with =."))

	def before_insert(self) -> None:
		validate_tenant_id(self.tenant_id)
		self.added_by = frappe.session.user
		self.status = "Active"
		self.client_id = get_next_client_id(self.team)

	def after_insert(self) -> None:
		settings = self.get_client().register_peer(self.tenant_id, self.client_id, self.public_key)
		self.db_set(
			{
				"address": settings["address"],
				"allowed_ips": "\n".join(settings["allowed_ips"]),
				"endpoint": settings["endpoint"],
				"gateway_public_key": settings["public_key"],
			}
		)

	def on_trash(self) -> None:
		self.get_client().remove_peer(self.tenant_id, self.client_id)

	def remove(self) -> bool:
		"""Take the device off its gateway and delete it or leave it Removing when the gateway is down."""
		try:
			# the caller already checked access and a leaving member may hold no server:wireguard
			frappe.delete_doc(self.doctype, self.name, ignore_permissions=True)
		except WireGuardGatewayError as error:
			self.db_set({"status": "Removing", "last_error": str(error)})
			return False

		return True

	@frappe.whitelist(methods=["POST"])
	def retry_removal(self) -> bool:
		"""Operator action: try the gateway again for a device stuck in Removing."""
		self.check_permission("delete")
		return self.remove()

	@property
	def tenant_id(self) -> int:
		return frappe.get_cached_value("Team", self.team, "tenant_id")

	def get_client(self) -> WireGuardGatewayClient:
		return Region.get_wireguard_client(self.region)


def get_next_client_id(team: str) -> int:
	# shortcut: deleted device ids are not reused so scan for gaps if a team nears the limit
	device = frappe.qb.DocType("WireGuard Device")
	highest = frappe.qb.from_(device).select(Max(device.client_id)).where(device.team == team).run()[0][0]
	client_id = (highest or 0) + 1
	if client_id > MAXIMUM_CLIENT_ID:
		frappe.throw(_("This team has reached the limit of WireGuard devices."))

	return client_id


def remove_departed_devices(team) -> None:
	"""Queue removal of devices whose member left and of every device of an archived team."""
	members = [] if team.status == "Archived" else [m.user for m in team.members if m.status == "Active"]
	filters = {"team": team.name, "status": "Active"}
	if members:
		filters["added_by"] = ("not in", members)
	if not frappe.db.exists("WireGuard Device", filters):
		return

	frappe.db.set_value("WireGuard Device", filters, "status", "Removing")
	frappe.enqueue(
		"central.infrastructure.doctype.wireguard_device.wireguard_device.remove_pending_devices",
		enqueue_after_commit=True,
	)


def remove_pending_devices() -> None:
	for name in frappe.get_all("WireGuard Device", {"status": "Removing"}, pluck="name"):
		frappe.get_doc("WireGuard Device", name).remove()


def restore_devices(region: str) -> int:
	"""Send every Active device of a region to its gateway again and store the settings it returns."""
	client = Region.get_wireguard_client(region)
	nodes = {(peer["tenant_id"], peer["client_id"]): peer["node_id"] for peer in client.list_peers()}

	device, team = frappe.qb.DocType("WireGuard Device"), frappe.qb.DocType("Team")
	rows = (
		frappe.qb.from_(device)
		.join(team)
		.on(team.name == device.team)
		.select(device.name, team.tenant_id, device.client_id, device.public_key)
		.where((device.region == region) & (device.status == "Active"))
		.run(as_dict=True)
	)
	client.replace_peers(
		[
			{
				"tenant_id": row.tenant_id,
				"client_id": row.client_id,
				"public_key": row.public_key,
				"node_id": nodes.get((row.tenant_id, row.client_id), ""),
			}
			for row in rows
		]
	)

	# a device without a surviving node gets a new one so its address can change
	peers = {(peer["tenant_id"], peer["client_id"]): peer for peer in client.list_peers()}
	for row in rows:
		peer = peers[(row.tenant_id, row.client_id)]
		frappe.db.set_value(
			"WireGuard Device",
			row.name,
			{
				"address": peer["address"],
				"endpoint": peer["endpoint"],
				"gateway_public_key": peer["public_key"],
			},
		)

	return len(rows)


def on_doctype_update() -> None:
	frappe.db.add_unique("WireGuard Device", ["team", "client_id"])
	frappe.db.add_index("WireGuard Device", ["status"])
