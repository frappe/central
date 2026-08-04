# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Trust Tier Level money limits move from single columns to per-currency rows.

`max_spend` / `min_cumulative_paid` were bare numbers on the level, so one
ladder couldn't serve INR and USD teams (₹4,000 != $4,000). They are now the
`Trust Tier Threshold` child table, keyed by currency. The legacy numbers were
effectively INR, so backfill one INR row per level from them, then drop the
orphan columns.

Idempotent: a level that already has threshold rows is skipped; the column drop
is guarded by has_column. Inserts the child rows directly (not via the parent
doc) so the entry-tier currency-coverage validation can't trip mid-backfill.
"""

import frappe


def execute():
	has_legacy = frappe.db.has_column("Trust Tier Level", "max_spend")

	for name in frappe.get_all("Trust Tier Level", pluck="name"):
		if frappe.db.exists("Trust Tier Threshold", {"parent": name}):
			continue  # already migrated
		max_spend = (frappe.db.get_value("Trust Tier Level", name, "max_spend") if has_legacy else 0) or 0
		min_cumulative_paid = (
			frappe.db.get_value("Trust Tier Level", name, "min_cumulative_paid")
			if frappe.db.has_column("Trust Tier Level", "min_cumulative_paid")
			else 0
		) or 0
		frappe.get_doc(
			{
				"doctype": "Trust Tier Threshold",
				"parent": name,
				"parenttype": "Trust Tier Level",
				"parentfield": "thresholds",
				"idx": 1,
				"currency": "INR",
				"max_spend": max_spend,
				"min_cumulative_paid": min_cumulative_paid,
			}
		).insert(ignore_permissions=True)

	for column in ("max_spend", "min_cumulative_paid"):
		if frappe.db.has_column("Trust Tier Level", column):
			frappe.db.sql_ddl(f"ALTER TABLE `tabTrust Tier Level` DROP COLUMN `{column}`")
