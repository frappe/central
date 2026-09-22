# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class ImageOffering(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.infrastructure.doctype.image_offering_tag.image_offering_tag import ImageOfferingTag

		available_in: DF.Literal["Server", "Signup", "Both"]
		description: DF.SmallText | None
		enabled: DF.Check
		logo: DF.AttachImage | None
		offering_key: DF.Data
		required_tags: DF.Table[ImageOfferingTag]
		title: DF.Data
	# end: auto-generated types

	def validate(self) -> None:
		if not re.fullmatch(r"[a-z][a-z0-9-]*", self.offering_key or ""):
			frappe.throw(_("Use lowercase letters, numbers and hyphens for the offering key."))

		if not self.is_new() and self.has_value_changed("offering_key"):
			frappe.throw(_("The offering key cannot change after creation."))

		self.get_image_tags()

	def get_image_tags(self) -> dict[str, str]:
		"""Build the Atlas selector without allowing query separators in a tag."""
		tags = {}
		for row in self.required_tags:
			row.key = (row.key or "").strip()
			row.value = (row.value or "").strip()
			if (
				not row.key
				or not row.value
				or any(character in row.key + row.value for character in ",:\r\n")
			):
				frappe.throw(_("Image tags need a key and value without commas, colons or line breaks."))

			if row.key in tags:
				frappe.throw(_("Image tag {0} is repeated.").format(row.key))
			tags[row.key] = row.value

		if not tags:
			frappe.throw(_("Add at least one image tag to define this offering."))

		return tags

	@frappe.whitelist(methods=["POST"])
	def preview_images(self, atlas_instance: str, offset: int = 0) -> dict:
		"""1. Require operator write access before previewing regional System images."""
		from central.integrations.images import preview_images

		self.check_permission("write")
		return preview_images(self.name, atlas_instance, offset)


def on_doctype_update() -> None:
	frappe.db.add_index("Image Offering", ["enabled", "available_in"])


def ensure_default_offerings() -> None:
	"""Create default product choices without replacing an operator's configuration."""
	for key, title, flow, description, tags in (
		("pilot", "Pilot", "Both", "Pilot with a Frappe bench and one prepared site.", {"purpose": "pilot"}),
		(
			"ubuntu",
			"Ubuntu",
			"Server",
			"A plain Ubuntu server without Pilot.",
			{"purpose": "base", "os": "Ubuntu"},
		),
	):
		if frappe.db.exists("Image Offering", key):
			continue

		frappe.get_doc(
			{
				"doctype": "Image Offering",
				"offering_key": key,
				"title": title,
				"enabled": 1,
				"available_in": flow,
				"description": description,
				"required_tags": [{"key": name, "value": value} for name, value in tags.items()],
			}
		).insert()
