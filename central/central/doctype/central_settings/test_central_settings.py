# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.integrations.atlas import MAXIMUM_METADATA_BYTES

FLAG_FIELDS = {
	"addons": "enable_addons",
	"llm": "enable_llm_service",
	"pdf": "enable_pdf_print_service",
	"email": "enable_email_delivery_service",
	"storage": "enable_object_storage_service",
	"public_ipv4": "enable_public_ipv4",
	"public_ipv6": "enable_public_ipv6",
	"firewall": "enable_firewall",
}


class IntegrationTestCentralSettings(IntegrationTestCase):
	def _set(self, **flags: int):
		# set_single_value invalidates the Single's cache, so the next
		# get_cached_doc in feature_flags() sees these writes.
		for field, value in flags.items():
			frappe.db.set_single_value("Central Settings", field, value)

	def tearDown(self):
		self._set(**dict.fromkeys(FLAG_FIELDS.values(), 0))

	def test_feature_flags_expose_every_flag(self):
		flags = frappe.get_cached_doc("Central Settings").feature_flags()
		self.assertEqual(set(flags), set(FLAG_FIELDS))

	def test_signup_image_age_patch_seeds_missing_value_and_preserves_operator_settings(self):
		from central.patches.v0_0.seed_signup_image_minimum_age import execute

		frappe.db.delete(
			"Singles", {"doctype": "Central Settings", "field": "signup_image_minimum_age_minutes"}
		)
		execute()
		self.assertEqual(
			frappe.db.get_single_value("Central Settings", "signup_image_minimum_age_minutes"), 30
		)

		for minutes in (0, 60):
			frappe.db.set_single_value("Central Settings", "signup_image_minimum_age_minutes", minutes)
			execute()
			self.assertEqual(
				frappe.db.get_single_value("Central Settings", "signup_image_minimum_age_minutes"), minutes
			)

	def test_feature_flags_reflect_the_checks(self):
		self._set(enable_addons=1, enable_llm_service=1, enable_pdf_print_service=0)
		flags = frappe.get_cached_doc("Central Settings").feature_flags()
		self.assertTrue(flags["addons"])
		self.assertTrue(flags["llm"])
		self.assertFalse(flags["pdf"])
		self.assertFalse(flags["storage"])

	def test_feature_flags_are_plain_bools(self):
		self._set(enable_llm_service=1)
		self.assertIs(frappe.get_cached_doc("Central Settings").feature_flags()["llm"], True)
		self.assertIs(frappe.get_cached_doc("Central Settings").feature_flags()["pdf"], False)

	def test_new_server_network_option_is_refused_while_its_flag_is_off(self):
		for requested in ((True, False, False), (False, True, False), (False, False, True)):
			with self.assertRaises(frappe.ValidationError):
				frappe.get_cached_doc("Central Settings").require_new_server_network_options(*requested)

		frappe.get_cached_doc("Central Settings").require_new_server_network_options(False, False, False)

	def test_new_server_network_option_is_allowed_once_its_flag_is_on(self):
		self._set(enable_public_ipv4=1, enable_public_ipv6=1, enable_firewall=1)

		frappe.get_cached_doc("Central Settings").require_new_server_network_options(True, True, True)

	def test_common_site_config_must_be_a_json_object_that_fits_in_metadata(self):
		self.addCleanup(frappe.db.set_single_value, "Central Settings", "common_site_config", None)

		for value in ('["a"]', "not json", f'{{"key": "{"x" * MAXIMUM_METADATA_BYTES}"}}'):
			settings = frappe.get_doc("Central Settings")
			settings.common_site_config = value
			with self.assertRaises(frappe.ValidationError):
				settings.save()

		settings = frappe.get_doc("Central Settings")
		settings.common_site_config = '{"raven_push_notification_server_url": "https://relay.test"}'
		settings.save()

	def test_help_links_send_an_empty_url_as_none_so_the_console_hides_it(self):
		url = "https://support.test/help/my-tickets/new"
		saved = {
			fieldname: frappe.db.get_single_value("Central Settings", fieldname)
			for fieldname in ("support_ticket_url", "feedback_url")
		}
		self.addCleanup(frappe.db.set_single_value, "Central Settings", saved)
		frappe.db.set_single_value("Central Settings", {"support_ticket_url": url, "feedback_url": ""})

		links = frappe.get_cached_doc("Central Settings").help_links()

		self.assertEqual(links, {"support_ticket_url": url, "feedback_url": None})
