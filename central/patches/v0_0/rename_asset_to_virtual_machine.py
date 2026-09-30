# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Rename the `Asset` DocType to `Virtual Machine` — that is what the product, and
Atlas's own doctype for the same resource, already call it.

`frappe.rename_doc("DocType", ...)` is the doctype-rename special case: it updates
every Link/Table field's `options` across the schema, renames the physical table
(`tabAsset` -> `tabVirtual Machine`), and tolerates the old doctype's controller
module no longer existing on disk. Runs pre_model_sync, before the renamed
doctype's own JSON is synced back onto the now-renamed table.

`Asset.cluster` is not renamed here — see `spec/DELIVERY.md` §5: renaming a field
right after the doctype rename touches the same table twice at once.

Guarded for a fresh site that never had the old doctype.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Asset"):
		return
	frappe.rename_doc("DocType", "Asset", "Virtual Machine", force=True, show_alert=False)
