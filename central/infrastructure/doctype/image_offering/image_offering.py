# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.integrations.images import APP_PURPOSE
from central.utils.units import MIB_PER_GIB


class ImageOffering(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.infrastructure.doctype.image_offering_tag.image_offering_tag import ImageOfferingTag

		available_in: DF.Literal["Server", "Signup", "Both"]
		description: DF.SmallText | None
		display_order: DF.Int
		enabled: DF.Check
		logo: DF.AttachImage | None
		minimum_memory_mib: DF.Int
		offering_key: DF.Data
		plan_category: DF.Link | None
		required_tags: DF.Table[ImageOfferingTag]
		title: DF.Data
	# end: auto-generated types

	def validate(self) -> None:
		if not re.fullmatch(r"[a-z][a-z0-9-]*", self.offering_key or ""):
			frappe.throw(_("Use lowercase letters, numbers and hyphens for the offering key."))

		if not self.is_new() and self.has_value_changed("offering_key"):
			frappe.throw(_("The offering key cannot change after creation."))

		self.get_image_tags()
		self.validate_plan_category()

	def validate_plan_category(self) -> None:
		if not self.plan_category:
			return

		if frappe.db.get_value("Plan Category", self.plan_category, "provision_target") != "Server":
			frappe.throw(_("Select a plan category that provisions a server."))

	def validate_custom_size(
		self, sub_category: str | None, memory_gib: float, is_current: bool = False
	) -> None:
		"""Refuse a custom size outside this offering's plan family or below its minimum memory.
		`is_current` marks the profile the server already runs, which it keeps."""
		family = frappe.db.get_value("Plan Sub-Category", sub_category, "category") if sub_category else None
		if self.plan_category and not is_current and family != self.plan_category:
			frappe.throw(_("Custom sizes are not available for this server. Choose a plan from the list."))

		if memory_gib * MIB_PER_GIB < self.minimum_memory_mib:
			frappe.throw(
				_("This server needs at least {0} GB of memory. Choose a size with more memory.").format(
					f"{self.minimum_memory_mib / MIB_PER_GIB:g}"
				)
			)

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
	def preview_images(self, region: str, offset: int = 0) -> dict:
		"""1. Require operator write access before previewing regional System images."""
		from central.integrations.images import preview_images

		self.check_permission("write")

		return preview_images(self.name, region, offset)


def on_doctype_update() -> None:
	frappe.db.add_index("Image Offering", ["enabled", "available_in"])


def ensure_default_offerings() -> None:
	"""Create default product choices without replacing an operator's configuration. They show
	in the order listed here."""
	offerings = (
		("pilot", "Frappe", "Both", "A Frappe bench, ready for your apps.", {"purpose": "pilot"}),
		(
			"apps",
			"Apps",
			"Server",
			"Ready-to-run software such as Redis and MariaDB.",
			{"purpose": APP_PURPOSE},
		),
		(
			"ubuntu",
			"Ubuntu",
			"Server",
			"A plain Ubuntu server.",
			{"purpose": "base", "os": "Ubuntu", "minimal": "false"},
		),
	)
	for order, (key, title, flow, description, tags) in enumerate(offerings, start=1):
		if frappe.db.exists("Image Offering", key):
			continue

		frappe.get_doc(
			{
				"doctype": "Image Offering",
				"offering_key": key,
				"title": title,
				"display_order": order,
				"enabled": 1,
				"available_in": flow,
				"description": description,
				"required_tags": [{"key": name, "value": value} for name, value in tags.items()],
			}
		).insert()
