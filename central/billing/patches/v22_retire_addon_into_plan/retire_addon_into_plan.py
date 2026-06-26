# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Retire the Add-on doctype: fold each into a metered single-resource Plan (ADR 0008).

After ADR 0007 unified rates under Catalog Rate and gave us single-resource `simple`
plans, Add-on became a near-duplicate of Plan carrying only billing metadata. This patch
folds it in: the billing behaviour (billing_type / billing_interval / pricing_mode) now
lives on Plan Category, and metering resolves the metered Plan by its single include's
resource_type. Every Add-on becomes a Plan; its Catalog Rate rows are repointed from
priced_doctype=Add-on to Plan.

Billing-neutral: a migrated overage resolves the same rate it did as an Add-on. The Plan
is named after the Add-on, so the rate rows (priced_for = the name) only need their
priced_doctype flipped — ids stay stable.

Idempotent: gated on the legacy `Add-on` table still existing; a re-run after the doctype
is gone is a no-op.
"""

import frappe

from central.billing.catalog.taxonomy_setup import ensure_catalog_masters

# Former Add-on pricing_mode -> the metered Plan Category that now carries it.
_TARGET_CATEGORY = {"Live": "Live Metered Resources", "Grandfathered": "Metered Resources"}


def execute():
	# The new Plan Category billing fields + the metered categories migrated plans
	# attach to. reload_doc so the columns are present even on a standalone re-run.
	frappe.reload_doc("billing", "doctype", "plan_category")
	ensure_catalog_masters()

	if frappe.db.exists("DocType", "Add-on") and frappe.db.table_exists("Add-on"):
		for addon in frappe.get_all(
			"Add-on", fields=["name", "title", "resource_type", "unit", "pricing_mode"]
		):
			_migrate_addon(addon)
		# Remove the DocType record now that nothing references it. We never instantiate
		# an Add-on document, so the now-deleted controller module is never imported.
		frappe.delete_doc("DocType", "Add-on", force=True, ignore_missing=True)

	# Drop the now-orphaned table. Deleting the DocType record does not always drop the
	# backing table, so do it explicitly. `IF EXISTS` keeps it idempotent and avoids a
	# stale cached table-list misfiring right after the DocType delete above.
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabAdd-on`")


def _migrate_addon(addon):
	category = _TARGET_CATEGORY.get(addon.pricing_mode, "Metered Resources")

	if not frappe.db.exists("Plan", addon.name):
		plan = frappe.get_doc(
			{
				"doctype": "Plan",
				"title": addon.title or addon.name,
				"category": category,
				"billing_cycle": "Monthly",
				"is_active": 1,
				"includes": [
					{"resource_type": addon.resource_type, "quantity": 0, "unit": addon.unit}
				],
			}
		)
		# Name the Plan after the Add-on so its Catalog Rate rows keep their ids.
		plan.flags.name_set = True
		plan.name = addon.name
		# The uniqueness rule (one active metered plan per resource type) was never
		# enforced for Add-ons — keep the first, deactivate any duplicate so the
		# migration never throws on legacy two-Add-ons-for-one-resource data.
		if _resource_already_metered(addon.resource_type):
			plan.is_active = 0
		plan.insert(ignore_permissions=True)

	# priced_for already equals the new Plan's name; just flip the doctype. (The Add-on
	# rows themselves are dropped wholesale when the DocType is deleted, in execute().)
	frappe.db.set_value(
		"Catalog Rate",
		{"priced_doctype": "Add-on", "priced_for": addon.name},
		"priced_doctype",
		"Plan",
		update_modified=False,
	)


def _resource_already_metered(resource_type: str) -> bool:
	"""True if an active metered single-resource Plan already covers this resource."""
	metered_cats = frappe.get_all("Plan Category", filters={"billing_type": "Metered"}, pluck="name")
	plans = frappe.get_all(
		"Plan", filters={"category": ["in", metered_cats], "is_active": 1}, pluck="name"
	)
	for p in plans:
		includes = frappe.get_all("Plan Includes", filters={"parent": p}, pluck="resource_type")
		if len(includes) == 1 and includes[0] == resource_type:
			return True
	return False
