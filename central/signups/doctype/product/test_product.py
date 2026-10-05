# Copyright (c) 2026, frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.api.signups import get_product
from central.site_provisioning import create_trial_site

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestProduct(IntegrationTestCase):
	"""A product names the app its trial starts with, and only an enabled one takes signups."""

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

	def start(self, product: str):
		"""Start a trial, keeping the mock that would ask the region for an image."""
		with (
			patch("central.site_provisioning.resolve_team", return_value="any-team"),
			patch("central.site_provisioning.validated_subdomain", return_value="acme"),
			patch("central.site_provisioning.trial_configuration", return_value={}) as configuration,
			patch("central.site_provisioning.submit_request"),
		):
			try:
				create_trial_site(None, "acme", "key", product)
			finally:
				self.configuration = configuration

	def test_a_product_trial_starts_with_its_app(self):
		self.product("raven-test")

		self.start("raven-test")

		self.configuration.assert_called_once_with("any-team", "raven")

	def test_a_disabled_or_unknown_product_is_refused_before_the_region_is_asked(self):
		self.product("raven-off", enabled=0)

		for product in ("raven-off", "no-such-product"):
			with self.subTest(product=product):
				with self.assertRaises(frappe.ValidationError):
					self.start(product)

				self.configuration.assert_not_called()

	def test_the_signup_pages_read_branding_of_an_enabled_product_only(self):
		self.product("raven-test")
		self.product("raven-off", enabled=0)

		self.assertEqual(get_product("raven-test").subtitle, "Chat for your team")
		self.assertIsNone(get_product("raven-off"))

	def test_the_operator_preview_asks_the_region_for_the_product_app(self):
		product = self.product("raven-test")

		with (
			patch("central.site_provisioning.signup_offering", return_value="pilot"),
			patch("central.integrations.images.preview_images") as preview,
		):
			product.preview_images("par-2")

		preview.assert_called_once_with(
			"pilot",
			"par-2",
			0,
			extra_tags={"has_site": "1", "frappe_version": "develop", "app": "raven"},
		)

	def test_a_product_key_is_a_lowercase_slug(self):
		with self.assertRaises(frappe.ValidationError):
			self.product("Raven App")
