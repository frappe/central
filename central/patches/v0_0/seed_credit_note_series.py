# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stamp the credit note series on sites that already saved Billing Settings."""

import frappe


def execute():
	if not frappe.db.get_single_value("Billing Settings", "series_credit_note"):
		frappe.db.set_single_value("Billing Settings", "series_credit_note", "CN/.TFY./.#####")
