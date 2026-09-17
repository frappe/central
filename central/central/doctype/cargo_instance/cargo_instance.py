import frappe
from frappe import _
from frappe.model.document import Document

# Both URLs are handed onward -- one to pilots to post telemetry at, one to Central's own
# callers. Without a scheme allowlist `validate_url` passes `javascript:` and `data:`.
VALID_SCHEMES = ("http", "https")


class CargoInstance(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		base_url: DF.Data | None
		region: DF.Link
		registered_at: DF.Datetime | None
		status: DF.Literal["Draft", "Registered", "Disabled"]
		telemetry_base_url: DF.Data | None
		webhook_secret: DF.Password | None
	# end: auto-generated types

	"""One Cargo host, and the region it provisions for.

	A Cargo host never calls Central: it signs webhooks with `webhook_secret`, and Central
	calls it for the services it runs."""

	def validate(self) -> None:
		self.validate_base_url()
		self.validate_telemetry_url()

	def validate_telemetry_url(self) -> None:
		"""If a telemetry URL is given, it must be a valid URL. If not given, it is cleared."""
		self.telemetry_base_url = (self.telemetry_base_url or "").strip().rstrip("/") or None
		if self.telemetry_base_url and not frappe.utils.validate_url(
			self.telemetry_base_url, valid_schemes=VALID_SCHEMES
		):
			frappe.throw(_("Telemetry URL must be a valid URL."), frappe.ValidationError)

	def validate_base_url(self) -> None:
		"""If a base URL is given, it must be a valid URL. If not given, it is cleared."""
		self.base_url = (self.base_url or "").strip().rstrip("/") or None
		if self.base_url and not frappe.utils.validate_url(self.base_url, valid_schemes=VALID_SCHEMES):
			frappe.throw(_("Base URL must be a valid URL."), frappe.ValidationError)

	@staticmethod
	def telemetry_url_for(region: str) -> str | None:
		"""Where a region's pilots ship metrics and logs, or None while that region has no
		enrolled Cargo. Read by name -- the autoname is `CARGO-{region}` -- so it comes off
		the request cache rather than the database on every token a pilot asks for."""
		telemetry_base_url = frappe.db.get_value(
			"Cargo Instance",
			{"region": region, "status": "Registered"},
			"telemetry_base_url",
			cache=True,
		)

		return telemetry_base_url or None
