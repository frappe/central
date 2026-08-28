# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""`Subscription.billing_group` -> `Subscription.project`, alongside the
Billing Group -> Project doctype rename.

Runs **post_model_sync** — `rename_field` copies data from the old column into
the new one, so the new `project` column (added by this migrate's doctype sync,
per the already-renamed `subscription.json`) must already exist; the old
`billing_group` column still holds every subscription's real tag at this point,
since a schema sync only ever adds columns, never drops them. The orphaned
`billing_group` column is then dropped explicitly.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	if frappe.db.has_column("Subscription", "billing_group") and frappe.db.has_column(
		"Subscription", "project"
	):
		rename_field("Subscription", "billing_group", "project")
		frappe.db.sql_ddl("ALTER TABLE `tabSubscription` DROP COLUMN `billing_group`")
