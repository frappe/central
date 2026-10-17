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

	def test_app_rollout_rejects_steps_out_of_range(self):
		for fieldname, value in (
			("app_rollout_start_percent", 0),
			("app_rollout_step_percent", 101),
			("app_rollout_interval_hours", 0),
			("app_rollout_max_percent", -1),
			("app_rollout_max_percent", 101),
			("app_rollout_failure_percent", 0),
			("app_rollout_failure_percent", 101),
			("app_rollout_minimum_servers", 0),
		):
			settings = frappe.get_doc("Central Settings")
			settings.set(fieldname, value)
			with self.subTest(fieldname=fieldname), self.assertRaises(frappe.ValidationError):
				settings.save()

	def test_app_rollout_accepts_a_max_percent_of_0_to_stop_rollouts(self):
		settings = frappe.get_doc("Central Settings")
		settings.app_rollout_max_percent = 0
		settings.save()
