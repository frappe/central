# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Align the Plan Configurator with the taxonomy masters (ADR 0007).

Two existing-DB fixes on top of the doctype changes:

1. The `configurator_builder` Select (Plan Category) and its fetched mirror
   (Plan Configurator.builder) move to Title Case — `vm_rungs` → `VM Rungs`,
   `simple` → `Simple` — to match every other Select option in the app.
2. Plan Configurator drops its `plan_class` Select: the optimisation profile is
   now the `sub_category` link (the Plan Sub-Category under the category). Carry
   the old plan_class onto sub_category where it maps to a real VM sub-category
   ("Custom" mapped to none), then drop the column. The `new_sub_category` Data
   field also goes — a custom sub-category is now minted inline via the Link.

Idempotent: the casing maps only rows still on the old value; the backfill/drops
are gated on the legacy columns still existing.
"""

import frappe

_BUILDER_TITLECASE = {"vm_rungs": "VM Rungs", "simple": "Simple"}
# Old plan_class value -> seeded Plan Sub-Category under VM Plans. "Custom" maps to none.
VM_SUB_CATEGORIES = {"General", "CPU Optimised", "Memory Optimised", "Storage Optimised"}


def execute():
	_titlecase_builder("Plan Category", "configurator_builder")
	_titlecase_builder("Plan Configurator", "builder")
	_backfill_configurator_sub_category()
	_drop_column("plan_class")
	_drop_column("new_sub_category")


def _titlecase_builder(doctype: str, field: str):
	"""Recase the stored builder value in place (only rows still on the old value)."""
	for old, new in _BUILDER_TITLECASE.items():
		frappe.db.set_value(doctype, {field: old}, field, new, update_modified=False)


def _backfill_configurator_sub_category():
	"""Carry each configurator's plan_class onto sub_category where it maps to a real
	VM sub-category and sub_category isn't already set. Gated on the legacy column."""
	if not frappe.db.has_column("Plan Configurator", "plan_class"):
		return
	# plan_class is no longer in the doctype meta (only the live DB column), so read
	# it through the query builder by column rather than frappe.get_all's field check.
	cfg = frappe.qb.DocType("Plan Configurator")
	rows = frappe.qb.from_(cfg).select(cfg.name, cfg.plan_class, cfg.sub_category).run(as_dict=True)
	for row in rows:
		if row.sub_category or row.plan_class not in VM_SUB_CATEGORIES:
			continue
		frappe.db.set_value(
			"Plan Configurator", row.name, "sub_category", row.plan_class, update_modified=False
		)


def _drop_column(column: str):
	if frappe.db.has_column("Plan Configurator", column):
		frappe.db.sql_ddl(f"ALTER TABLE `tabPlan Configurator` DROP COLUMN `{column}`")
