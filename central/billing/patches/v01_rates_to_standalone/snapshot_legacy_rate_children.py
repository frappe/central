# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Pre-model-sync: snapshot the legacy child-table rate rows.

`Plan Rate` and `Add-on Rate` child tables are being merged into one standalone
`Catalog Rate` DocType (ERPNext `Item Price` style). This patch runs *before* the
DocType JSONs are migrated, while `tabPlan Rate` / `tabAdd-on Rate` still carry
the child-table `parent` column. We copy each row into a scratch table so the
post-model-sync patch can rebuild it as a `Catalog Rate` document — even in the
(unlikely) case the schema sync later drops the child-only columns.

Idempotent: re-snapshotting just rebuilds the scratch table from current data.
Safe no-op: if the table is already standalone (no `parent` column) there is
nothing legacy to snapshot.
"""

import frappe

# Legacy child DocType -> nothing here yet; the parent link is added post-sync.
RATE_DOCTYPES = ("Plan Rate", "Add-on Rate")


def execute():
	for doctype in RATE_DOCTYPES:
		if not frappe.db.table_exists(doctype):
			continue

		if not frappe.db.has_column(doctype, "parent"):
			# Already standalone (or never a child) — nothing to snapshot.
			continue

		table = f"tab{doctype}"
		scratch = scratch_table(doctype)
		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{scratch}`")
		frappe.db.sql_ddl(
			f"""CREATE TABLE `{scratch}` AS
				SELECT `name`, `parent`, `cluster`, `currency`, `rate`, `creation`, `owner`
				FROM `{table}`
				WHERE `parent` IS NOT NULL AND `parent` != ''"""
		)


def scratch_table(doctype: str) -> str:
	"""`Plan Rate` -> `__legacy_plan_rate_rows`."""
	return "__legacy_" + frappe.scrub(doctype) + "_rows"


def raw_table_exists(table_name: str) -> bool:
	"""Existence check for a plain (non-DocType) table, e.g. a scratch table."""
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.tables "
			"WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
			table_name,
		)
	)
