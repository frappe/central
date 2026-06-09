# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Post-model-sync: merge legacy rate child rows into one `Catalog Rate` DocType.

Pairs with `snapshot_legacy_rate_children` (pre-model-sync). The two child tables
(`Plan Rate` on `Plan`, `Add-on Rate` on `Add-on`) are replaced by a single
standalone `Catalog Rate` DocType (ERPNext `Item Price` style) that links its
parent via a Dynamic Link: `priced_doctype` (Plan | Add-on) + `priced_for`.

For each snapshotted legacy row we INSERT a `Catalog Rate` document
(`priced_doctype` from the source table, `priced_for` = old `parent`, plus
`cluster`/`currency`/`rate`), named `{priced_for}-{cluster}-{currency}`. Rows
can't be renamed in place because they move into a different table. Once a legacy
table is drained we drop its DocType + table.

Self-guarding + idempotent:
  - if `Catalog Rate` doesn't exist yet (conversion not shipped) but legacy data
    is waiting, raise so the patch is NOT marked executed and re-runs once the
    DocType lands (the pre-sync snapshot is preserved meanwhile);
  - rows whose target identity already exists are skipped;
  - the scratch table is dropped only after its rows are migrated.
"""

import frappe

from central.billing.patches.v01_rates_to_standalone.snapshot_legacy_rate_children import (
	raw_table_exists,
	scratch_table,
)

TARGET_DOCTYPE = "Catalog Rate"
# Legacy child DocType -> the `priced_doctype` value its rows belong to.
LEGACY = {
	"Plan Rate": "Plan",
	"Add-on Rate": "Add-on",
}


def execute():
	pending = [dt for dt in LEGACY if raw_table_exists(scratch_table(dt))]
	if not pending:
		return  # nothing snapshotted, or a previous run already finished

	if not frappe.db.exists("DocType", TARGET_DOCTYPE):
		# Legacy data is waiting but the new DocType hasn't shipped. Raise (don't
		# return) so this patch stays un-executed and re-runs once it lands.
		frappe.throw(
			f"Cannot migrate rate rows: `{TARGET_DOCTYPE}` does not exist yet. "
			"Deploy the Catalog Rate DocType and re-run migrate.",
			title="rates_to_standalone: Catalog Rate not deployed",
		)

	for legacy_dt, priced_doctype in LEGACY.items():
		scratch = scratch_table(legacy_dt)
		if not raw_table_exists(scratch):
			continue

		rows = frappe.db.sql(
			f"SELECT `parent`, `cluster`, `currency`, `rate` FROM `{scratch}`",
			as_dict=True,
		)
		for row in rows:
			_migrate_row(priced_doctype, row)

		frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{scratch}`")
		_drop_legacy_doctype(legacy_dt)


def _migrate_row(priced_doctype: str, row: dict) -> None:
	priced_for = row["parent"]
	cluster = (row.get("cluster") or "").strip() or None
	currency = row["currency"]
	target = "-".join(p for p in (priced_for, cluster, currency) if p)

	if frappe.db.exists(TARGET_DOCTYPE, target):
		return  # already migrated

	doc = frappe.new_doc(TARGET_DOCTYPE)
	doc.update(
		{
			"priced_doctype": priced_doctype,
			"priced_for": priced_for,
			"cluster": cluster,
			"currency": currency,
			"rate": row["rate"],
		}
	)
	doc.insert(ignore_permissions=True, set_name=target)


def _drop_legacy_doctype(legacy_dt: str) -> None:
	"""Remove the now-empty legacy child DocType and its orphaned table."""
	if frappe.db.exists("DocType", legacy_dt):
		frappe.delete_doc("DocType", legacy_dt, force=True, ignore_permissions=True)
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{legacy_dt}`")
