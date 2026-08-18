# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Merge `Service API Key` + `Site Service Credential` into one `Service Credential`.

The two were near-duplicate credential tables differing only in scope: a per-site
credential (`site`) versus a team-level API key (`label`). They share the same fields,
the same provider secret, and the same token meter, so they fold into one DocType with a
`subject_type` discriminator (`Site` / `Team`).

`name` (the random hash) is preserved so the encrypted `api_key` in the `__Auth` table
stays resolvable — we only repoint its `doctype`, never re-encrypt. Idempotent: gated on
the legacy tables still existing; a re-run after they are dropped is a no-op.
"""

import frappe

# source doctype -> (subject_type value, the scope column that source carries)
_SOURCES = {
	"Site Service Credential": ("Site", "site"),
	"Service API Key": ("Team", "label"),
}

# Columns common to both source tables, carried over verbatim. `name` is preserved so the
# api_key secret in __Auth stays resolvable once its doctype is repointed.
_SHARED_COLUMNS = [
	"name",
	"creation",
	"modified",
	"modified_by",
	"owner",
	"docstatus",
	"idx",
	"managed_service",
	"status",
	"gateway_url",
	"provider_ref",
	"last_usage_total",
	"api_key",
]


def execute():
	# reload_doc so the target table exists even on a standalone re-run.
	frappe.reload_doc("services", "doctype", "service_credential")

	for source, (subject_type, scope_column) in _SOURCES.items():
		if frappe.db.table_exists(source):
			_copy_rows(source, subject_type, scope_column)
			_repoint_secrets(source)

	for source in _SOURCES:
		# Deleting the DocType drops its backing table; nothing instantiates these docs
		# any more, so their removed controller modules are never imported.
		if frappe.db.exists("DocType", source):
			frappe.delete_doc("DocType", source, force=True, ignore_missing=True)


def _copy_rows(source: str, subject_type: str, scope_column: str) -> None:
	src = frappe.qb.DocType(source)
	read_columns = [*_SHARED_COLUMNS, scope_column]
	rows = frappe.qb.from_(src).select(*(getattr(src, column) for column in read_columns)).run(as_dict=True)

	# Skip rows already copied so a re-run after a partial pass never double-inserts.
	values = [
		(*(row[column] for column in _SHARED_COLUMNS), subject_type, row[scope_column])
		for row in rows
		if not frappe.db.exists("Service Credential", row["name"])
	]
	if not values:
		return

	target = frappe.qb.DocType("Service Credential")
	target_columns = [*_SHARED_COLUMNS, "subject_type", scope_column]
	frappe.qb.into(target).columns(*target_columns).insert(*values).run()


def _repoint_secrets(source: str) -> None:
	# The api_key secret lives in `__Auth` keyed by (doctype, name, fieldname); name is
	# preserved above, so repointing the doctype keeps get_password working untouched.
	auth = frappe.qb.Table("__Auth")
	(
		frappe.qb.update(auth)
		.set(auth.doctype, "Service Credential")
		.where((auth.doctype == source) & (auth.fieldname == "api_key"))
		.run()
	)
