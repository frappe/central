# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog taxonomy moves from VM-shaped Select enums to masters (ADR 0007, #75).

`Plan.plan_class` and the `resource_type` Select on Plan Includes / Add-on were
frozen enums. They become `Plan Category` + `Plan Sub-Category` (replacing plan_class)
and `Resource Type` links.

The master *seed* lives in `taxonomy_setup.ensure_catalog_masters` (shared with the
install/migrate/test hooks, since patches are skipped on fresh installs). This patch
is the existing-DB migration on top of that seed: backfill plans from the old
plan_class column, drop it, and flag IP/Snapshot. Because a Link stores the master's
name verbatim, the resource_type strings (Compute, Memory, …) need no rewrite.

Idempotent: the backfill is gated on the legacy column still existing; the drop is
has_column-guarded. Uses db.set_value so legacy IP/Snapshot includes don't trip the
new category validation mid-migration.
"""

import frappe

from central.billing.catalog.taxonomy_setup import ensure_catalog_masters

# Old plan_class value -> seeded Plan Sub-Category under VM Plans. "Custom" maps to none.
VM_SUB_CATEGORIES = ["General", "CPU Optimised", "Memory Optimised", "Storage Optimised"]


def execute():
	ensure_catalog_masters()
	_backfill_plans()
	_drop_plan_class_column()
	_flag_ip_snapshot_rows()


def _backfill_plans():
	"""Every existing plan is a VM plan; carry its plan_class onto sub_category.

	Gated on the legacy column still existing — `category` can't be the sentinel
	because its field default pre-fills existing rows when the column is added.
	Once plan_class is dropped there's nothing to backfill, so a re-run is a no-op.
	"""
	if not frappe.db.has_column("Plan", "plan_class"):
		return
	# One read of (name, plan_class) for the whole fleet, not a get_value per plan.
	# plan_class is no longer in the doctype meta (only the live DB column), so go
	# through the query builder by column rather than frappe.get_all's field check.
	plan = frappe.qb.DocType("Plan")
	rows = frappe.qb.from_(plan).select(plan.name, plan.plan_class).run(as_dict=True)
	for row in rows:
		sub_category = row.plan_class if row.plan_class in VM_SUB_CATEGORIES else None
		frappe.db.set_value(
			"Plan",
			row.name,
			{"category": "VM Plans", "sub_category": sub_category},
			update_modified=False,
		)


def _drop_plan_class_column():
	if frappe.db.has_column("Plan", "plan_class"):
		frappe.db.sql_ddl("ALTER TABLE `tabPlan` DROP COLUMN `plan_class`")


def _flag_ip_snapshot_rows():
	"""IP/Snapshot leave the core resource set (#77). Don't drop — surface them."""
	for doctype in ("Plan Includes", "Add-on"):
		rows = frappe.get_all(
			doctype,
			filters={"resource_type": ["in", ["IP", "Snapshot"]]},
			fields=["name", "resource_type"],
		)
		for r in rows:
			# logger (not print): visible in the site log + `bench console`, and not
			# swallowed when the patch runs headlessly under `bench migrate`.
			frappe.logger("billing").info(
				f"[catalog_taxonomy #75] {doctype} {r.name} uses resource_type "
				f"{r.resource_type!r} — reclassify as an Add-on in #77."
			)
