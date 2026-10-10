# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

PRODUCT_KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
# A Frappe app's module name, which Cargo writes as the image's app tag.
# A path on the site itself, never another host.
LANDING_ROUTE_PATTERN = re.compile(r"/[A-Za-z0-9_/-]*")
APP_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class Product(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		landing_route: DF.Data | None
		logo: DF.AttachImage | None
		product_key: DF.Data
		signup_app: DF.Data
		subtitle: DF.SmallText | None
		title: DF.Data
	# end: auto-generated types

	def validate(self) -> None:
		if not PRODUCT_KEY_PATTERN.fullmatch(self.product_key or ""):
			frappe.throw(_("Use lowercase letters, numbers and hyphens for the product key."))

		if not self.is_new() and self.has_value_changed("product_key"):
			frappe.throw(_("The product key cannot change after creation."))

		if not APP_NAME_PATTERN.fullmatch(self.signup_app or ""):
			frappe.throw(_("Use the app's module name for the signup app, such as raven."))

		if self.landing_route and not LANDING_ROUTE_PATTERN.fullmatch(self.landing_route):
			frappe.throw(_("Use a path on the site for the landing route, such as /raven."))

	@frappe.whitelist(methods=["POST"])
	def preview_images(self, region: str, offset: int = 0) -> dict:
		"""1. Require operator write access before previewing the region's trial images."""
		from central.integrations.images import preview_images
		from central.site_provisioning import product_image_tags, signup_offering

		self.check_permission("write")
		return preview_images(
			signup_offering(), region, offset, extra_tags=product_image_tags(self.signup_app)
		)


def get_signup_product(product_key: str) -> Product:
	"""The enabled product a signup names, or a refusal the customer can read."""
	if not frappe.db.exists("Product", {"name": product_key, "enabled": 1}):
		frappe.throw(_("This product is not available for signup."))

	return frappe.get_cached_doc("Product", product_key)
