# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Stamp the GSTIN sweep knobs on sites that already saved the Single.

A field added after the save reads back as 0: a zero window would re-check every
GSTIN daily, and a zero limit would never check one.
"""

import frappe

DEFAULTS = {"gst_status_refresh_days": 7, "gst_status_daily_limit": 500}


def execute():
	for field, value in DEFAULTS.items():
		if not frappe.db.get_single_value("Billing Settings", field):
			frappe.db.set_single_value("Billing Settings", field, value)
