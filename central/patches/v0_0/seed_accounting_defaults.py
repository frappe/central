# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stamp the accounting defaults on sites that already saved Billing Settings.

A field added after the save reads back blank, which would leave invoices with no
naming series and the setup with no item or print format to create.
"""

import frappe

DEFAULTS = {
	"service_item": "Cloud Hosting",
	"item_group": "Services",
	"sac_code": "998315",
	"series_india_b2b": "B2B/.TFY./.#####",
	"series_india_b2c": "B2C/.TFY./.#####",
	"series_overseas": "EXP/.TFY./.#####",
	"series_receipt_voucher": "RV/.TFY./.######",
	"invoice_print_format": "Cloud Tax Invoice",
	"receipt_voucher_print_format": "Cloud Receipt Voucher",
}


def execute():
	for field, value in DEFAULTS.items():
		if not frappe.db.get_single_value("Billing Settings", field):
			frappe.db.set_single_value("Billing Settings", field, value)
