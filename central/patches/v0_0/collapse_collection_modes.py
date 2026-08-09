# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collapse Stripe Auto and E-Mandate into Auto Charge (ADR 0022, #106).

Both named a provider pretending to be a behaviour, and under Stripe India an
Indian card mandate is the two of them at once. What the customer experiences is
the same in either case: we debit the saved method without them present. Whether
a ceiling applies is derived from the currency and the rail, so the mode no longer
has to carry it.

Runs post_model_sync, after the Select's option list has been migrated. Idempotent:
only rows still holding a retired value are touched.
"""

import frappe

RETIRED = ("Stripe Auto", "E-Mandate")


def execute():
	if not frappe.db.table_exists("Billing Profile"):
		return
	if not frappe.db.has_column("Billing Profile", "collection_mode"):
		return
	profile = frappe.qb.DocType("Billing Profile")
	frappe.qb.update(profile).set(profile.collection_mode, "Auto Charge").where(
		profile.collection_mode.isin(RETIRED)
	).run()
