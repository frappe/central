# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""An Indian billing address names its state, because GST depends on it."""

import inspect

import frappe

from central.billing.api import billing_api, dashboard
from central.billing.tests.test_dashboard import CustomerDataBase
from central.billing.tests.utils import complete_billing_profile

TEAM = "team-cust"
ADDRESS = {"legal_name": "Acme Pvt Ltd", "address_line1": "1 Main Street", "city": "Pune"}


class TestIndianState(CustomerDataBase):
	def _profile(self) -> dict:
		return dashboard.get_billing_profile(TEAM)

	def test_an_indian_address_without_a_state_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			dashboard.save_billing_profile(TEAM, country="India", **ADDRESS)

	def test_an_indian_address_with_a_state_is_saved(self):
		dashboard.save_billing_profile(TEAM, country="India", state="Maharashtra", **ADDRESS)
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "state"), "Maharashtra")
		self.assertFalse(self._profile()["gst_state_missing"])
		self.assertIsNone(self._profile()["igst_rate"])

	def test_the_country_alone_is_saved_before_the_address(self):
		dashboard.save_billing_profile(TEAM, country="India")
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "currency"), "INR")

	def test_a_foreign_address_needs_no_state(self):
		dashboard.save_billing_profile(TEAM, country="Germany", **ADDRESS)
		self.assertFalse(self._profile()["gst_state_missing"])

	def test_a_profile_saved_without_a_state_still_saves_outside_the_form(self):
		complete_billing_profile(TEAM)
		frappe.db.set_value("Billing Profile", TEAM, "state", None)
		frappe.db.set_value("Tax Profile", TEAM, "output_tax_rate", 18)

		frappe.get_doc("Billing Profile", TEAM).save(ignore_permissions=True)

		self.assertTrue(self._profile()["gst_state_missing"])
		self.assertEqual(self._profile()["igst_rate"], 18)


class TestPilotIndianState(CustomerDataBase):
	"""The pilot API saves through the same rule as the console."""

	def setUp(self):
		super().setUp()
		frappe.local.pilot_credential = frappe._dict(team=TEAM)
		self.save = inspect.unwrap(billing_api.save_billing_profile)

	def tearDown(self):
		frappe.local.pilot_credential = None
		super().tearDown()

	def test_an_indian_address_without_a_state_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Select your state"):
			self.save(country="India", **ADDRESS)

	def test_an_indian_address_with_a_state_is_saved(self):
		self.assertTrue(self.save(country="India", state="Maharashtra", **ADDRESS)["saved"])
		self.assertEqual(frappe.db.get_value("Billing Profile", TEAM, "state"), "Maharashtra")
