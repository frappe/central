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
