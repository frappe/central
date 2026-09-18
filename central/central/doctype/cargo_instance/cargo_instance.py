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
		webhook_secret: DF.Password | None
	# end: auto-generated types

	"""One Cargo host, and the region it provisions for.

	A Cargo host never calls Central: it signs webhooks with `webhook_secret`, and Central
	calls it for the services it runs."""

	def validate(self) -> None:
		self.validate_base_url()

	def validate_base_url(self) -> None:
		"""If a base URL is given, it must be a valid URL. If not given, it is cleared."""
		self.base_url = (self.base_url or "").strip().rstrip("/") or None
		if self.base_url and not frappe.utils.validate_url(self.base_url, valid_schemes=VALID_SCHEMES):
			frappe.throw(_("Base URL must be a valid URL."), frappe.ValidationError)
