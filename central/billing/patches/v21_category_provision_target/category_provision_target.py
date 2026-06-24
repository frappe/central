# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Backfill Plan Category.provision_target so the create-server flow can filter to
provisionable families. Sets it from the taxonomy seed specs (VM Plans -> Server);
families with no provision target stay blank. Existing categories predate the field,
so seeding (which only creates absent rows) doesn't reach them — hence this patch.
"""

import frappe

from central.billing.catalog.taxonomy_setup import CATEGORIES


def execute():
	for spec in CATEGORIES:
		target = spec.get("provision_target")
		if target and frappe.db.exists("Plan Category", spec["category_name"]):
			frappe.db.set_value(
				"Plan Category", spec["category_name"], "provision_target", target, update_modified=False
			)
