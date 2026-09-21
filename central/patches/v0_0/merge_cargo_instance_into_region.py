# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Fold `Cargo Instance` into `Region` (spec/DELIVERY.md model cleanup).

Cargo Instance already linked to the Region it provisions for through a required,
unique `region` field — one Cargo per Region, just recorded as a second document.
Region now carries its connection directly, under `cargo_*` fields, next to the
Atlas connection the same record already holds. Copy each Cargo Instance's fields
onto its Region (by that link, since a Cargo Instance is not autonamed to match
one), then drop the doctype.

Runs post_model_sync, so Region already has the new columns and the Cargo Instance
table (if this site ever had one) still holds its data. Idempotent: a fresh install
never created `tabCargo Instance`, and a repeat run finds nothing left to copy.
"""

import frappe

FIELDS = ("base_url", "status", "registered_at")


def execute():
	if not frappe.db.table_exists("Cargo Instance"):
		return

	for row in frappe.get_all("Cargo Instance", fields=["name", "region", *FIELDS]):
		if not row.region or not frappe.db.exists("Region", row.region):
			frappe.log_error(title=f"Cargo Instance {row.name} named no Region to merge into")
			continue

		secret = frappe.utils.password.get_decrypted_password(
			"Cargo Instance", row.name, "webhook_secret", raise_exception=False
		)
		region = frappe.get_doc("Region", row.region)
		region.cargo_base_url = row.base_url
		region.cargo_status = row.status
		region.cargo_registered_at = row.registered_at
		if secret:
			region.cargo_webhook_secret = secret
		region.save(ignore_permissions=True)

	frappe.delete_doc("DocType", "Cargo Instance", force=True, ignore_missing=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabCargo Instance`")
