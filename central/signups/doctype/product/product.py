# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

PRODUCT_KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
# A Frappe app's module name, which Cargo writes as the image's app tag.
APP_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class Product(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		enabled: DF.Check
		logo: DF.AttachImage | None
		product_key: DF.Data
		signup_app: DF.Data
		subtitle: DF.SmallText | None
		title: DF.Data
	# end: auto-generated types

	_DOCTYPE_NAME = "Product"

	def validate(self) -> None:
		if not PRODUCT_KEY_PATTERN.fullmatch(self.product_key or ""):
			frappe.throw(_("Use lowercase letters, numbers and hyphens for the product key."))

		if not self.is_new() and self.has_value_changed("product_key"):
			frappe.throw(_("The product key cannot change after creation."))

		if not APP_NAME_PATTERN.fullmatch(self.signup_app or ""):
			frappe.throw(_("Use the app's module name for the signup app, such as raven."))


def get_signup_product(product_key: str) -> Product:
	"""The enabled product a signup names, or a refusal the customer can read."""
	if not frappe.db.exists("Product", {"name": product_key, "enabled": 1}):
		frappe.throw(_("This product is not available for signup."))

	return frappe.get_cached_doc("Product", product_key)
