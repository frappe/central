# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Migrate Payment Gateway single currency field to the Payment Gateway Currency
child table (issue #46).

For each existing Payment Gateway row that still carries the old `currency`
column value (a Data field), this patch inserts one Payment Gateway Currency
child row with is_default = 1. Idempotent: skips gateways that already have
child rows. The old `currency` column is left in place and can be dropped in a
subsequent clean-up patch once all sites have migrated.
"""

import frappe


def execute():
	gateways = frappe.get_all("Payment Gateway", fields=["name"])
	for gw in gateways:
		existing = frappe.get_all(
			"Payment Gateway Currency", {"parent": gw.name}, pluck="name"
		)
		if existing:
			continue

		# Read the old column directly — the field may have been removed from the
		# DocType JSON but the column survives in the DB until explicitly dropped.
		try:
			currency = frappe.db.sql(
				"SELECT currency FROM `tabPayment Gateway` WHERE name = %s", gw.name
			)
			currency = currency[0][0] if currency and currency[0][0] else None
		except Exception:
			currency = None

		if not currency:
			continue

		frappe.get_doc(
			{
				"doctype": "Payment Gateway Currency",
				"parenttype": "Payment Gateway",
				"parentfield": "currencies",
				"parent": gw.name,
				"currency": currency,
				"is_default": 1,
			}
		).insert(ignore_permissions=True)
