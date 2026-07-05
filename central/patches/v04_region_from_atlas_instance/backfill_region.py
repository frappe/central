# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Extract Region from Atlas Instance.

The console's map metadata (display_name, provider, country_code, latitude,
longitude) used to live on Atlas Instance — the same row that holds the admin
api_key/api_secret. It now lives on its own Region doctype, keyed by the region
code (one Atlas = one Region). This backfills a Region for every existing Atlas
Instance from the columns that are being retired.

Runs after model sync, so the Region table exists and the old Atlas Instance
columns still linger (Frappe never drops columns on field removal) — we read them
by raw SQL. Idempotent: a Region that already exists is left untouched.
"""

import frappe

_DISPLAY_COLUMNS = ("display_name", "provider", "country_code", "latitude", "longitude")


def execute():
	# Fresh install (or already migrated): the old columns never existed, so there
	# is nothing to lift onto Region.
	if not frappe.db.has_column("Atlas Instance", "latitude"):
		return

	columns = ", ".join(f"`{c}`" for c in _DISPLAY_COLUMNS)
	rows = frappe.db.sql(
		f"SELECT `name`, {columns} FROM `tabAtlas Instance`", as_dict=True
	)
	for row in rows:
		if frappe.db.exists("Region", row.name):
			continue
		region = frappe.new_doc("Region")
		region.region = row.name
		for column in _DISPLAY_COLUMNS:
			region.set(column, row.get(column))
		region.insert(ignore_permissions=True)
