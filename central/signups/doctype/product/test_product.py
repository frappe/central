# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestProduct(IntegrationTestCase):
	"""A product key is the stable name in a signup link."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.rollback)

	def product(self, product_key: str, enabled: int = 1):
		return frappe.get_doc(
			{
				"doctype": "Product",
				"product_key": product_key,
				"title": "Raven",
				"subtitle": "Chat for your team",
				"signup_app": "raven",
				"enabled": enabled,
			}
		).insert()

	def test_a_product_key_is_a_lowercase_slug(self):
		with self.assertRaises(frappe.ValidationError):
			self.product("Raven App")
