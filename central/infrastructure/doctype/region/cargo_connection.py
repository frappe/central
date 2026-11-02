# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

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

		self.cargo_webhook_secret = secret
		self.cargo_status = "Registered"
		self.cargo_registered_at = frappe.utils.now_datetime()
		self.save()

		return True


def get_cargo_machine_claims(token: str) -> dict:
	"""The claims of a machine token a region's Cargo signed with its webhook secret.

	1. The unverified `region` claim only selects the secret; it proves nothing.
	2. The region's Cargo must be Registered and hold a secret.
	3. The HS256 signature must match that secret, with the machine token audience.
	4. The token must name a machine and one of Cargo's node roles, or `cargo` for Cargo's own host."""
	import jwt

	try:
		region = jwt.decode(token, options={"verify_signature": False}).get("region")
		if (
			not isinstance(region, str)
			or frappe.db.get_value("Region", region, "cargo_status") != "Registered"
		):
			raise jwt.InvalidTokenError

		secret = get_decrypted_password("Region", region, "cargo_webhook_secret", raise_exception=False)
		if not secret:
			raise jwt.InvalidTokenError

		claims = jwt.decode(
			token,
			secret,
			algorithms=["HS256"],
			audience="central:datum-credential",
			issuer="cargo",
			options={"require": ["iss", "aud", "iat"]},
		)
	except jwt.PyJWTError:
		frappe.throw(_("Invalid machine token."), frappe.AuthenticationError)

	if not claims.get("machine") or claims.get("role") not in ("gateway", "storage", "telemetry", "cargo"):
		frappe.throw(_("Invalid machine token."), frappe.AuthenticationError)

	return claims


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
