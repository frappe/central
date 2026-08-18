# Copyright (c) 2026, frappe and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

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
