# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Remove per-project credit budgets and card earmarking (breaking change,
requested directly): with only one consolidated invoice again, a project's
"own budget" / "own card" had no invoice left to settle against — it was
bookkeeping with nothing underneath it. `Credit Ledger Entry.billing_group`
and `Payment Method.billing_group` are dropped outright, not renamed; nothing
downstream reads them once `revenue/credits.py` and `payments/collection.py`
stop writing them.
"""

import frappe


def execute():
	if frappe.db.has_column("Credit Ledger Entry", "billing_group"):
		frappe.db.sql_ddl("ALTER TABLE `tabCredit Ledger Entry` DROP COLUMN `billing_group`")
	if frappe.db.has_column("Payment Method", "billing_group"):
		frappe.db.sql_ddl("ALTER TABLE `tabPayment Method` DROP COLUMN `billing_group`")
