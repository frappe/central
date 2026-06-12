# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing Profile gains an explicit `currency`; `billing_mode` is retired.

Currency used to be derived implicitly from a team's Price Lock (defaulting to
INR), so a team could never declare USD vs INR before money moved. It is now a
first-class, user-set Billing Profile field. For existing profiles, seed it from
the team's price-lock currency so nothing changes under them. `billing_mode`
(prepaid/postpaid) was never read by any charge/settlement code — billing is
credits-first-then-card for everyone — so its column is dropped.

Idempotent: backfill only fills a blank currency; the column drop is guarded.
"""

import frappe


def execute():
	# Backfill currency on profiles that predate the field.
	for profile in frappe.get_all(
		"Billing Profile", filters={"currency": ["in", [None, ""]]}, pluck="name"
	):
		currency = frappe.db.get_value("Price Lock", {"team": profile}, "currency")
		if currency:
			frappe.db.set_value("Billing Profile", profile, "currency", currency,
								update_modified=False)

	# Retire the unused billing_mode column.
	if frappe.db.has_column("Billing Profile", "billing_mode"):
		frappe.db.sql_ddl("ALTER TABLE `tabBilling Profile` DROP COLUMN `billing_mode`")
