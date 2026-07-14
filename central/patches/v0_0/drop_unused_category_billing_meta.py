# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Drop the unused billing-metadata fields from Plan Category (ADR 0007 follow-up).

`default_billing_type`, `default_pricing_mode`, `billable_unit`, and `meter_kind`
were seeded on the taxonomy masters but never read by any billing/metering/pricing
code path (no consumer, no fetch_from). They were descriptive intent that was never
wired up, so they're removed; this drops the orphan columns left behind.

Idempotent: each drop is gated on the column still existing.
"""

import frappe

_COLUMNS = ("default_billing_type", "default_pricing_mode", "billable_unit", "meter_kind")


def execute():
	for column in _COLUMNS:
		if frappe.db.has_column("Plan Category", column):
			frappe.db.sql_ddl(f"ALTER TABLE `tabPlan Category` DROP COLUMN `{column}`")
