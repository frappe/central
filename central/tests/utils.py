# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared fixtures for central tests."""

import frappe


def ensure_region(region: str, **overrides) -> str:
	"""Create the region a test puts resources in, with the fields an Atlas call needs."""
	if not frappe.db.exists("Region", region):
		frappe.get_doc(
			{
				"doctype": "Region",
				"region": region,
				"atlas_base_url": f"https://{region}.atlas.example.test",
				"status": "Active",
				"api_key": "test-key",
				"api_secret": "test-secret",
				**overrides,
			}
		).insert(ignore_permissions=True)
	elif overrides:
		frappe.db.set_value("Region", region, overrides, update_modified=False)
	return region


# The two used to be separate doctypes; tests still name both.
ensure_atlas_instance = ensure_region
