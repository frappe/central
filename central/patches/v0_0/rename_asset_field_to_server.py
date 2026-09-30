# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""`asset`/`asset_id` -> `server` on every doctype that links to a Virtual
Machine — the field name had stayed `asset` through the DocType rename
(`rename_asset_to_virtual_machine`); this finishes it so the field matches its
own label ("Server") everywhere.

Runs **post_model_sync** — `rename_field` copies data from the old column into
the new one, so each new column (added by this migrate's doctype sync, per the
already-renamed doctype JSON) must already exist; the old column still holds
every record's real link at this point, since a schema sync only ever adds
columns, never drops them. Each orphaned old column is then dropped
explicitly.
"""

import frappe
from frappe.model.utils.rename_field import rename_field

# (doctype, old fieldname, new fieldname)
RENAMES = (
	("Site", "asset", "server"),
	("Resource Action", "asset", "server"),
	("Site Domain", "asset", "server"),
	("Pilot Credential", "asset", "server"),
	("Subscription", "asset_id", "server_id"),
)


def execute():
	for doctype, old_fieldname, new_fieldname in RENAMES:
		if frappe.db.has_column(doctype, old_fieldname) and frappe.db.has_column(doctype, new_fieldname):
			rename_field(doctype, old_fieldname, new_fieldname)
			frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{old_fieldname}`")
