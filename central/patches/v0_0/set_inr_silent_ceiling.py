# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Put the RBI ceiling on every INR gateway currency row (ADR 0022, #106).

The silent-debit ceiling used to be a constant on the Razorpay adapter. It is now
a property of (gateway, currency), because Stripe India settles INR under the same
₹15,000 rule while Stripe USD has no ceiling at all. On a migrated site the new
columns come up empty, and an empty ceiling reads as "no ceiling" — so until this
runs, an INR debit of any size looks chargeable off-session.

Idempotent: only rows that are empty or above the ceiling are touched.
"""

import frappe

from central.billing.gateways.capabilities import INR_SILENT_CEILING


def execute():
	if not frappe.db.table_exists("Payment Gateway Currency"):
		return
	if not frappe.db.has_column("Payment Gateway Currency", "max_silent_charge"):
		return

	row = frappe.qb.DocType("Payment Gateway Currency")
	unset_or_too_high = (
		row.max_silent_charge.isnull()
		| (row.max_silent_charge == 0)
		| (row.max_silent_charge > INR_SILENT_CEILING)
	)
	frappe.qb.update(row).set(row.max_silent_charge, INR_SILENT_CEILING).where(
		(row.currency == "INR") & unset_or_too_high
	).run()
	frappe.qb.update(row).set(row.requires_predebit_notice, 1).where(row.currency == "INR").run()
