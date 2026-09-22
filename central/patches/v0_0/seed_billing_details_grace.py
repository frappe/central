# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stamp the billing-details grace period on sites that already saved the Single.

A Single keeps only the values it was saved with, so a field added after that save
reads back as 0 — and a grace of zero would page the operators about every held
invoice the day this ships. Written once, and only when nobody has set it.
"""

import frappe


def execute():
	if frappe.db.get_single_value("Billing Settings", "billing_details_grace_days"):
		return
	frappe.db.set_single_value("Billing Settings", "billing_details_grace_days", 30)
