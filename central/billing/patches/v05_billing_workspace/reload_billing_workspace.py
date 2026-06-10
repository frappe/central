# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Re-import the Billing desk Workspace from its app JSON (issue #44 follow-up).

The merge carried over a thin Billing workspace from the standalone app (it still
named `app: "billing"`). It was rebuilt ERPNext-style — a shortcut row plus
function-grouped cards over all Billing DocTypes. On a site that already holds the
old workspace, the normal migrate sync skips it: for non-DocType records the
importer keeps the DB copy when its `modified` is newer than the file's. A forced
`reload_doc` re-imports it regardless, so existing sites converge on the new
layout. Idempotent.
"""

import frappe


def execute() -> None:
	frappe.reload_doc("billing", "workspace", "billing", force=True)
