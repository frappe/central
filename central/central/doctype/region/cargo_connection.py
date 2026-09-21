# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Everything about a region's Cargo that only Cargo cares about.

Mixed into `Region` (see `region.py`). Cargo has no polled "Test Connection" the
way Atlas does: a host reports itself in by webhook once it is up, so readiness
here is a fact Central is told, not one it checks. Keep Atlas-specific fields and
logic in `atlas_connection.py` instead of here.
"""

from __future__ import annotations

import frappe
from frappe import _

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
