# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Everything about a region's Atlas that only Atlas cares about.

Mixed into `Region` (see `region.py`). Nothing here is Cargo's concern: Cargo has no
VMs to gateway to, and checks its own reachability a different way (a self-report,
not a polled connection). Keep Cargo-specific fields and logic in `cargo_connection.py`
instead of here.
"""

from __future__ import annotations

import ipaddress

import frappe
from frappe import _

from central.errors import AtlasConnectionError
from central.iam import user_has_operator_bypass

BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
VM_HOST_INFIX = "-vm-"
ADMIN_HOST_PREFIX = f"admin{VM_HOST_INFIX}"
SITE_HOST_PREFIX = "site-"


class AtlasConnectionMixin:
	"""The Atlas half of Region: its endpoint, numeric ID, proxy zone, and signed-access
	health. `Region` mixes this in alongside `CargoConnectionMixin`."""

	def validate_atlas_connection(self) -> None:
		self.proxy_domain = self._clean_proxy_domain()
		self.atlas_region_id = str(self.atlas_region_id).strip() if self.atlas_region_id is not None else None
		self.atlas_region_id = self.atlas_region_id or None
		if self.atlas_region_id is not None:
			self.atlas_region_id = str(self.get_atlas_region_id())

		if self.has_value_changed("base_url") or self.has_value_changed("atlas_region_id"):
			self.reachable = 0
			self.connection_checked_at = None
			self.connection_error = None

	def get_vm_gateway_url(self, mesh_address: str | None) -> str | None:
		"""The bench admin URL the regional proxy routes to this VM, or None when the
		region has no proxy zone or the VM has no mesh address yet."""
		host = self.get_vm_admin_host(mesh_address)
		return f"https://{host}" if host else None

	def get_vm_admin_host(self, mesh_address: str | None) -> str | None:
		"""The hostname the regional proxy routes to this VM's bench admin."""
		return self._proxy_host(ADMIN_HOST_PREFIX, mesh_address)

	def get_vm_site_host(self, mesh_address: str | None) -> str | None:
		"""The public hostname of the site every Pilot image bakes, which the image's own
		`site-*` alias answers on. It follows from the machine alone, so Central knows the
		address before the site has ever been reached."""
		return self._proxy_host(SITE_HOST_PREFIX, mesh_address)

	def _proxy_host(self, prefix: str, mesh_address: str | None) -> str | None:
		if not self.proxy_domain or not mesh_address:
			return None

		try:
			label = _proxy_label(mesh_address)
		except ValueError:
			frappe.throw(_("Atlas returned an invalid server mesh address."), AtlasConnectionError)

		return f"{prefix}{label}.{self.proxy_domain}"

	def _clean_proxy_domain(self) -> str | None:
		"""A bare zone: no wildcard, no scheme, no path, no trailing dot."""
		domain = (self.proxy_domain or "").strip().lower().removeprefix("*.").rstrip(".")
		if not domain:
			return None
		if "/" in domain or ":" in domain or "." not in domain:
			frappe.throw(_("Set the proxy domain to a bare zone, such as par-2.fc.frappe.dev."))

		return domain

	def get_atlas_region_id(self) -> int:
		value = self.atlas_region_id or ""
		if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 65535:
			frappe.throw(
				_("Set the Atlas region ID to a whole number from 0 to 65535."), AtlasConnectionError
			)

		return int(value)

	@frappe.whitelist(methods=["POST"])
	def test_connection(self) -> dict:
		"""Check signed regional access and persist an operator-readable result."""
		from central.integrations.atlas import AtlasClient

		if not user_has_operator_bypass():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		self.check_permission("write")

		# Keep the saved configuration stable until its remote check finishes.
		self.flags.for_update = True
		self.reload()

		try:
			AtlasClient.for_operator(self).check_connection()
		except AtlasConnectionError as error:
			result = {"reachable": False, "error": str(error)}
		else:
			result = {"reachable": True, "error": None}

		self.db_set(
			{
				"reachable": int(result["reachable"]),
				"connection_checked_at": frappe.utils.now_datetime(),
				"connection_error": result["error"],
			}
		)
		return result


def is_auto_routed_label(label: str) -> bool:
	"""Report whether the regional proxy routes a hostname from its own label.

	The proxy decodes the mesh address from the base-36 token of a `site-*` or `*-vm-*`
	label and answers before it reads its site map, so it refuses a map entry for one."""
	return label.startswith(SITE_HOST_PREFIX) or VM_HOST_INFIX in label


def _proxy_label(mesh_address: str) -> str:
	"""Encode a mesh address the way the regional proxy decodes a hostname label: the six
	hextets after the /32 mesh prefix as one base-36 number, VM identity above tenant."""
	hextets = ipaddress.IPv6Address(mesh_address).exploded.split(":")
	value = 0
	for hextet in (*hextets[4:], *hextets[2:4]):
		value = value << 16 | int(hextet, 16)

	label = ""
	while value:
		value, remainder = divmod(value, 36)
		label = BASE36_DIGITS[remainder] + label

	return label or "0"
