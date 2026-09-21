# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Fold `Atlas Instance` into `Region` (spec/DELIVERY.md model cleanup).

An Atlas Instance was always `autoname:field:region`, so its name was already the
Region it belonged to — one record for the connection, one for the geography, of
the same thing. Region now carries both. Copy each Atlas Instance's connection
fields onto its matching Region row (they share a name), then drop the doctype.

Runs post_model_sync, so Region already has the new columns and the Atlas Instance
table (if this site ever had one) still holds its data. Idempotent: a fresh install
never created `tabAtlas Instance`, and a repeat run finds nothing left to copy.
"""

import frappe

HEALTH_FIELDS = ("reachable", "last_synced_at", "connection_checked_at", "connection_error")


def execute():
	if not frappe.db.table_exists("Atlas Instance"):
		return

	for row in frappe.get_all(
		"Atlas Instance",
		fields=["name", "base_url", "proxy_domain", "status", "atlas_region_id", *HEALTH_FIELDS],
	):
		if not frappe.db.exists("Region", row.name):
			# The required Link should make this impossible; skip rather than invent a Region.
			frappe.log_error(title=f"Atlas Instance {row.name} had no matching Region to merge into")
			continue

		secret = frappe.utils.password.get_decrypted_password(
			"Atlas Instance", row.name, "webhook_secret", raise_exception=False
		)
		region = frappe.get_doc("Region", row.name)
		region.update(
			{
				"base_url": row.base_url,
				"proxy_domain": row.proxy_domain,
				"status": row.status,
				"atlas_region_id": row.atlas_region_id,
			}
		)
		if secret:
			region.webhook_secret = secret
		region.save(ignore_permissions=True)
		# `validate` resets reachable/connection_checked_at/connection_error whenever
		# base_url or atlas_region_id changes, which they always do on this first save
		# (moving from unset). Restore the real connection health straight after.
		region.db_set({field: row.get(field) for field in HEALTH_FIELDS}, update_modified=False)

	frappe.delete_doc("DocType", "Atlas Instance", force=True, ignore_missing=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabAtlas Instance`")
