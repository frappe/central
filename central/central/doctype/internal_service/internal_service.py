# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class InternalService(Document):
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
		service_type: DF.Literal["Cargo", "Datum"]
		status: DF.Literal["Draft", "Registered", "Disabled"]
	# end: auto-generated types

	"""One service Central runs in one region, and how a host of it is enrolled.

	Central never calls these hosts. Cargo enrols itself: it is issued a short-lived
	bootstrapping token and spends it to collect the two tokens it runs on. Datum has no
	enrolment, so its row is written by hand."""

	def autoname(self) -> None:
		"""`CARGO-<region>`, which is what a Cargo token's `instance` claim names. Renaming
		a row would stop every token already issued for it from verifying."""
		self.name = f"{self.service_type.upper()}-{self.region}"

	def validate(self) -> None:
		self.base_url = (self.base_url or "").rstrip("/") or None

	@frappe.whitelist()
	def issue_bootstrapping_token(self) -> dict:
		"""Operator action: mint the token that setup.sh takes as
		`CENTRAL_BOOTSTRAPPING_TOKEN`. Shown once, and spent by the host on enrolment."""
		if "System Manager" not in frappe.get_roles():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		from central.sso import mint_service_bootstrapping_token

		token = mint_service_bootstrapping_token(self.name, self.region, self.service_type)
		self.bootstrapping_token = token
		self.status = "Draft"
		self.save(ignore_permissions=True)

		return {"bootstrapping_token": token}

	@staticmethod
	def url_for(region: str, service_type: str) -> str:
		"""Where a region's service answers. Throws rather than returning a URL nobody set."""
		url = frappe.db.get_value(
			"Internal Service",
			{"region": region, "service_type": service_type, "status": ("!=", "Disabled")},
			"base_url",
		)
		if not url:
			frappe.throw(_("{0} has no {1} to reach in {2}.").format(service_type, "URL", region))

		return url

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
