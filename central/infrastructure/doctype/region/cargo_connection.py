# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Everything about a region's Cargo that only Cargo cares about.

Mixed into `Region` (see `region.py`). Cargo has no polled "Test Connection" the
way Atlas does: Central checks its health endpoint only to know when to register it,
and after that Cargo reports itself in by webhook. Keep Atlas-specific fields and
logic in `atlas_connection.py` instead of here.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils.password import set_encrypted_password

from central.errors import CargoConnectionError
from central.iam import user_has_operator_bypass

# Both URLs are handed onward -- one to pilots to post telemetry at, one to Central's own
# callers. Without a scheme allowlist `validate_url` passes `javascript:` and `data:`.
VALID_SCHEMES = ("http", "https")


class CargoConnectionMixin:
	"""The Cargo half of Region: its endpoint, registration state, and the secret it
	signs its own reports with. `Region` mixes this in alongside `AtlasConnectionMixin`."""

	def validate_cargo_connection(self) -> None:
		"""If a Cargo base URL is given, it must be a valid URL. If not given, it is cleared."""
		self.cargo_base_url = (self.cargo_base_url or "").strip().rstrip("/") or None
		if self.cargo_base_url and not frappe.utils.validate_url(
			self.cargo_base_url, valid_schemes=VALID_SCHEMES
		):
			frappe.throw(_("Cargo base URL must be a valid URL."), frappe.ValidationError)

	def get_cargo_url(self) -> str:
		"""The operator's Cargo address, or the one Atlas gives every Cargo it builds."""
		return self.cargo_base_url or self.get_service_url("cargo", self.name)

	@frappe.whitelist(methods=["POST"])
	def enroll_cargo(self) -> None:
		"""Operator action: register this region's Cargo now. A failure raises."""
		if not user_has_operator_bypass():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		self.check_permission("write")

		# Keep the saved configuration stable until this call finishes.
		self.flags.for_update = True
		self.reload()

		if not self.register_cargo():
			frappe.throw(_("Cargo has not answered a health check yet."), CargoConnectionError)

	def register_cargo(self) -> bool:
		"""Once Cargo answers, send it Central's receiver and a fresh secret, and return whether
		it is Registered. Atlas installs Cargo with a placeholder Central, so it reports nothing
		until this runs. A repeat only replaces the secret, so it is safe to retry."""
		from central.integrations.cargo import CargoClient

		client = CargoClient(self)
		if not client.is_answering():
			return False

		secret = frappe.generate_hash(length=32)
		client.configure_webhooks(secret)

		set_encrypted_password("Region", self.name, secret, "cargo_webhook_secret")
		self.db_set({"cargo_status": "Registered", "cargo_registered_at": frappe.utils.now_datetime()})
		return True


def register_pending_cargo() -> None:
	"""Register each Draft Cargo whose Atlas is enrolled. Atlas never reports when Cargo is up."""
	regions = frappe.get_all("Region", filters={"status": "Active", "cargo_status": "Draft"}, pluck="name")
	for name in regions:
		region = frappe.get_doc("Region", name)
		if not region.get_password("webhook_secret", raise_exception=False):
			continue

		try:
			region.register_cargo()
		except frappe.ValidationError:
			region.log_error("Cargo enrollment failed")
