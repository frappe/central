# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class MetalVPNProfile(Document):
	"""A VPN profile that an operator hands out to one user."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assigned_to: DF.Link | None
		configuration: DF.Password
		note: DF.SmallText | None
		status: DF.Literal["Available", "Assigned", "Archived"]
		usecase: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		if self.status != "Archived":
			self.status = "Assigned" if self.assigned_to else "Available"

	@frappe.whitelist(methods=["POST"])
	def download_profile(self) -> None:
		"""Send the profile as a file to a System Manager."""
		frappe.only_for("System Manager")

		frappe.response["filename"] = f"{self.name}.ovpn"
		frappe.response["filecontent"] = self.get_password("configuration")
		frappe.response["type"] = "download"


@frappe.whitelist(methods=["POST"])
def add_from_file(
	profile_name: str, file_url: str, usecase: str | None = None, note: str | None = None
) -> str:
	"""Create a profile from an uploaded text file, then delete the file so only the encrypted copy stays."""
	frappe.only_for("System Manager")

	file = frappe.get_doc("File", {"file_url": file_url, "is_private": 1})
	configuration = file.get_content()
	if isinstance(configuration, bytes):
		frappe.throw(_("The file is not a text profile."))

	profile = frappe.get_doc(
		{"doctype": "Metal VPN Profile", "configuration": configuration, "usecase": usecase, "note": note}
	)
	profile.name = profile_name
	profile.insert()
	file.delete()

	return profile.name
