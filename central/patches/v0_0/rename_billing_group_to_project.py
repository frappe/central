# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rename the `Billing Group` DocType to `Project` (breaking change, requested
directly — the "billing group" name never read naturally to partners organising
their own assets).

`frappe.rename_doc("DocType", ...)` is the doctype-rename special case: it
updates every Link/Table field's `options` across the schema, renames the
physical table (`tabBilling Group` -> `tabProject`), and tolerates the old
doctype's controller module no longer existing on disk (it never needs to
import it — only the core DocType controller). Runs pre_model_sync, before the
new `project.json` (with its extra `spending_limit` field) is synced onto the
now-renamed table.

Guarded for a fresh site that never had the old doctype.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Billing Group"):
		return
	frappe.rename_doc("DocType", "Billing Group", "Project", force=True, show_alert=False)
