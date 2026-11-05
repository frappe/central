# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from central.billing import settings


class TestBillingSettings(IntegrationTestCase):
	def tearDown(self):
		frappe.db.set_single_value("Billing Settings", "provision_teams_as_trial", 0)

	def test_provision_teams_as_trial_reads_the_single(self):
		frappe.db.set_single_value("Billing Settings", "provision_teams_as_trial", 1)
		self.assertIs(settings.provision_teams_as_trial(), True)

		frappe.db.set_single_value("Billing Settings", "provision_teams_as_trial", 0)
		self.assertIs(settings.provision_teams_as_trial(), False)


class TestDunningLadderSettings(IntegrationTestCase):
	def _validate(self, **values):
		doc = frappe.get_doc("Billing Settings")
		doc.update(values)
		doc.validate_dunning_ladder()

	def test_the_shipped_ladder_is_valid(self):
		self._validate(dunning_retry_interval_days=2, suspension_day=15, terminate_after_days=10)

	def test_a_retry_interval_below_one_day_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(dunning_retry_interval_days=0)

	def test_a_suspension_day_on_or_before_the_last_payment_day_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(suspension_day=10)

	def test_a_suspension_day_missing_from_a_month_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(suspension_day=29)

	def test_termination_on_the_suspension_day_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate(terminate_after_days=0)
