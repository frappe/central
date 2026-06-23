# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog taxonomy moves from VM-shaped Select enums to masters (ADR 0007, #75).

`Plan.plan_class` and the `resource_type` Select on Plan Includes / Add-on were
frozen enums — the proliferation trap one level down from plans. They become
`Plan Category` + `Plan Sub-Category` (replacing plan_class) and `Resource Type`
links.

Seeds the current VM taxonomy so nothing in flight breaks, then backfills.
Because a Link stores the master's name verbatim, the resource_type strings
(Compute, Memory, ...) need no rewrite — only the masters must exist for the
links to resolve. plan_class, however, is copied into category/sub_category and
its orphan column dropped.

Idempotent: seeds skip when present; the backfill only touches plans missing a
category; the column drop is has_column-guarded. Uses db.set_value for the
backfill so legacy IP/Snapshot includes don't trip the new category validation.
"""

import frappe

# Resource Types = every value the old enums could hold, so existing Plan
# Includes / Add-on links resolve. IP and Snapshot are seeded for continuity but
# are NOT in any category's allow-list — #77 reclassifies them as add-ons.
RESOURCE_TYPES = ["Compute", "Memory", "Disk", "Transfer", "IP", "Snapshot"]

VM_PLANS = {
	"category_name": "VM Plans",
	"configurator_builder": "vm_rungs",
	"sub_category_label": "Optimization profile",
	"default_billing_type": "Fixed",
	"default_pricing_mode": "Grandfathered",
	"billable_unit": "vCPU bundle / mo",
	"meter_kind": "None",
	"description": "Flat-rate compute bundles (vCPU + memory + disk + transfer).",
	"allowed": ["Compute", "Memory", "Disk", "Transfer"],
}

# Old plan_class value -> seeded Plan Sub-Category under VM Plans. "Custom" maps
# to nothing (a custom rung carries no profile).
VM_SUB_CATEGORIES = ["General", "CPU Optimised", "Memory Optimised", "Storage Optimised"]


def execute():
	_seed_resource_types()
	_seed_vm_category()
	_seed_vm_sub_categories()
	_backfill_plans()
	_drop_plan_class_column()
	_flag_ip_snapshot_rows()


def _seed_resource_types():
	for name in RESOURCE_TYPES:
		if not frappe.db.exists("Resource Type", name):
			frappe.get_doc({"doctype": "Resource Type", "resource_type_name": name}).insert(
				ignore_permissions=True
			)


def _seed_vm_category():
	if frappe.db.exists("Plan Category", VM_PLANS["category_name"]):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Plan Category",
			"category_name": VM_PLANS["category_name"],
			"configurator_builder": VM_PLANS["configurator_builder"],
			"sub_category_label": VM_PLANS["sub_category_label"],
			"default_billing_type": VM_PLANS["default_billing_type"],
			"default_pricing_mode": VM_PLANS["default_pricing_mode"],
			"billable_unit": VM_PLANS["billable_unit"],
			"meter_kind": VM_PLANS["meter_kind"],
			"description": VM_PLANS["description"],
			"allowed_resource_types": [{"resource_type": rt} for rt in VM_PLANS["allowed"]],
		}
	)
	doc.insert(ignore_permissions=True)


def _seed_vm_sub_categories():
	for name in VM_SUB_CATEGORIES:
		if not frappe.db.exists("Plan Sub-Category", name):
			frappe.get_doc(
				{
					"doctype": "Plan Sub-Category",
					"sub_category_name": name,
					"category": VM_PLANS["category_name"],
				}
			).insert(ignore_permissions=True)


def _backfill_plans():
	"""Every existing plan is a VM plan; carry its plan_class onto sub_category.

	Gated on the legacy column still existing — `category` can't be the sentinel
	because its field default pre-fills existing rows when the column is added.
	Once plan_class is dropped there's nothing to backfill, so a re-run is a no-op.
	set_value (not save) keeps legacy IP/Snapshot includes from tripping the new
	category validation mid-migration.
	"""
	if not frappe.db.has_column("Plan", "plan_class"):
		return
	for name in frappe.get_all("Plan", pluck="name"):
		plan_class = frappe.db.get_value("Plan", name, "plan_class")
		sub_category = plan_class if plan_class in VM_SUB_CATEGORIES else None
		frappe.db.set_value(
			"Plan",
			name,
			{"category": VM_PLANS["category_name"], "sub_category": sub_category},
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
			print(
				f"[v15 #75] {doctype} {r.name} uses resource_type {r.resource_type!r} — "
				f"reclassify as an Add-on in #77."
			)
