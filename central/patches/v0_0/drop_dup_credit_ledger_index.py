# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Drop the redundant index on Credit Ledger Entry.gateway_payment_id.

The field is `unique`, which already gives it an index (`gateway_payment_id`).
It also carried `search_index`, which added a second, non-unique index
(`gateway_payment_id_index`) over the same column — pure duplication. The
docfield flag is gone; this drops the leftover index (migrate never drops one on
its own). Idempotent: skipped if the index isn't there.
"""

import frappe

_TABLE = "tabCredit Ledger Entry"
_INDEX = "gateway_payment_id_index"


def execute():
	if frappe.db.has_index(_TABLE, _INDEX):
		frappe.db.sql(f"ALTER TABLE `{_TABLE}` DROP INDEX `{_INDEX}`")
