from __future__ import annotations

import ipaddress

import frappe
from frappe.model.document import Document


def next_free_ip(cidr: str, used: set[str]) -> str:
	"""The lowest host address in `cidr` not already taken — the first host (.1) is
	reserved for the hub, `used` are the Atlas peers already allocated. Pure (no DB),
	so it unit-tests without a host. Raises if the pool is exhausted."""
	net = ipaddress.ip_network(cidr, strict=False)
	hosts = net.hosts()
	hub = str(next(hosts))  # .1, the hub
	reserved = used | {hub}
	for host in net.hosts():
		address = str(host)
		if address not in reserved:
			return address
	raise frappe.ValidationError(f"Tunnel pool {cidr} is exhausted.")


class CentralTunnelSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		hub_endpoint: DF.Data | None
		hub_interface: DF.Data
		hub_private_key_path: DF.Data
		hub_public_key: DF.SmallText | None
		hub_status: DF.Literal["Uninitialized", "Active"]
		listen_port: DF.Int
		tunnel_cidr: DF.Data
	# end: auto-generated types

	def hub_address(self) -> str:
		"""The hub's address-with-mask on wg0, derived from the pool — the first host
		of `tunnel_cidr` (e.g. `10.88.0.1/16`)."""
		net = ipaddress.ip_network(self.tunnel_cidr, strict=False)
		return f"{next(net.hosts())}/{net.prefixlen}"

	def allocate_tunnel_ip(self) -> str:
		"""Allocate the next free Atlas `/32` host address from the pool (bare, e.g.
		`10.88.0.2`). The caller (Register orchestration) stores it on the
		`Atlas Instance` and forms the `/32` for `allowed-ips`."""
		return next_free_ip(self.tunnel_cidr, _used_tunnel_ips())

	@frappe.whitelist()
	def initialize_hub(self) -> dict:
		"""Operator action: bring up the hub interface (idempotent) and record its
		public key. Runs `hub-up.py` on the Central host via the local host-task
		runner, then stores the returned public key and flips `hub_status` to
		Active."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw("Not permitted.", frappe.PermissionError)

		from central.host_task import parse_result, run_host_task

		task = run_host_task(
			script="hub-up.py",
			variables={
				"PRIVATE_KEY_PATH": self.hub_private_key_path,
				"ADDRESS": self.hub_address(),
				"LISTEN_PORT": self.listen_port,
				"INTERFACE": self.hub_interface,
			},
		)
		result = parse_result(task.stdout)
		self.hub_public_key = result["public_key"]
		self.hub_status = "Active"
		self.save()
		return {"ok": True, "public_key": self.hub_public_key, "task": task.name}


def _used_tunnel_ips() -> set[str]:
	"""The Atlas peer addresses already allocated, read off `Atlas Instance`. Guarded
	on the column existing so allocation works before the Step-4 `tunnel_ip` field
	lands (and degrades to 'no peers yet' rather than erroring)."""
	if not frappe.db.has_column("Atlas Instance", "tunnel_ip"):
		return set()
	return {ip for ip in frappe.get_all("Atlas Instance", pluck="tunnel_ip") if ip}
