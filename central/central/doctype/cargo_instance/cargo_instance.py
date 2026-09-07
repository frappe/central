import frappe
from frappe import _
from frappe.model.document import Document


class CargoInstance(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		atlas_access_token: DF.Password | None
		base_url: DF.Data | None
		bootstrapping_token: DF.Password | None
		central_access_token: DF.Password | None
		region: DF.Link
		registered_at: DF.Datetime | None
		status: DF.Literal["Draft", "Registered", "Disabled"]
	# end: auto-generated types

	"""One Cargo host, and the region it provisions for.

	Central never calls a Cargo host. It issues a short-lived bootstrapping token, and the
	host spends it to collect the two tokens it runs on."""

	@frappe.whitelist()
	def issue_bootstrapping_token(self) -> dict:
		"""Operator action: mint the token that setup.sh takes as
		`CENTRAL_BOOTSTRAPPING_TOKEN`. Shown once, and spent by the host on enrolment."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		from central.sso import mint_cargo_bootstrapping_token

		token = mint_cargo_bootstrapping_token(self.name)
		self.bootstrapping_token = token
		self.status = "Draft"
		self.save(ignore_permissions=True)

		return {"bootstrapping_token": token}

	def record_enrolment(self, base_url: str, tokens: dict[str, str]) -> None:
		"""The host presented its bootstrapping token and collected its own."""
		self.update(
			{
				**tokens,
				"base_url": (base_url or "").rstrip("/") or None,
				"status": "Registered",
				"registered_at": frappe.utils.now_datetime(),
				"bootstrapping_token": None,
			}
		)
		self.save(ignore_permissions=True)
