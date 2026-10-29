# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Money records change only through billing code, never by hand in Desk or over REST."""

import frappe

from central.billing.platform.records import delete_billing_record, save_billing_record
from central.billing.tests.utils import BillingTestCase, ensure_team

TEAM = "team-money-records"


class TestMoneyRecordsAreReadOnly(BillingTestCase):
	def setUp(self):
		ensure_team(TEAM)
		frappe.db.delete("Invoice", {"team": TEAM})
		self.invoice = frappe.get_doc(
			{
				"doctype": "Invoice",
				"team": TEAM,
				"invoice_type": "Billable",
				"status": "Open",
				"period_start": "2026-09-01",
				"period_end": "2026-09-30",
				"currency": "INR",
				"subtotal": 100,
				"total": 100,
				"expected_collection": 100,
			}
		).insert(ignore_permissions=True)

	def test_an_edit_by_hand_is_refused_even_for_administrator(self):
		invoice = frappe.get_doc("Invoice", self.invoice.name)  # as Desk loads it
		invoice.total = 1
		with self.assertRaises(frappe.PermissionError):
			invoice.save()

	def test_a_delete_by_hand_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Invoice", self.invoice.name)

	def test_ignore_permissions_alone_does_not_allow_a_change(self):
		self.invoice.total = 1
		with self.assertRaises(frappe.PermissionError):
			self.invoice.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Invoice", self.invoice.name, ignore_permissions=True)

	def test_billing_code_may_still_change_it(self):
		self.invoice.total = 120
		save_billing_record(self.invoice)
		self.assertEqual(frappe.db.get_value("Invoice", self.invoice.name, "total"), 120)

		self.invoice.total = 130
		with self.assertRaises(frappe.PermissionError):
			self.invoice.save(ignore_permissions=True)

	def test_billing_code_may_still_delete_it(self):
		delete_billing_record(self.invoice)
		self.assertFalse(frappe.db.exists("Invoice", self.invoice.name))
