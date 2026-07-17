# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Title-case Billing Profile.collection_mode stored values (ADR 0005, #50).

collection_mode landed *after* the v08 Select title-casing sweep, so it still held
lower/snake_case values (stripe_auto, emandate, manual_checkout, prepaid,
action_required). Bring it in line with every other billing Select field. Runs
post_model_sync, after the field's option list has been migrated. Idempotent: each
update only touches rows still holding an old value.
"""

import frappe

RENAMES = {
	"stripe_auto": "Stripe Auto",
	"emandate": "E-Mandate",
	"manual_checkout": "Manual Checkout",
	"prepaid": "Prepaid",
	"action_required": "Action Required",
}


def execute():
	if not frappe.db.table_exists("Billing Profile"):
		return
	if not frappe.db.has_column("Billing Profile", "collection_mode"):
		return
	t = frappe.qb.DocType("Billing Profile")
	for old, new in RENAMES.items():
		frappe.qb.update(t).set(t.collection_mode, new).where(t.collection_mode == old).run()
