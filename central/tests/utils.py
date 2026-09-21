# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared fixtures for central tests."""

import frappe


def ensure_region(region: str) -> str:
	"""Create the Region master if it isn't there yet."""
	if not frappe.db.exists("Region", region):
		frappe.get_doc({"doctype": "Region", "region": region}).insert(ignore_permissions=True)
	return region


def ensure_atlas_instance(region: str, **overrides) -> str:
	"""Create the region a test wants to put resources in, connection-configured."""
	ensure_region(region)
	if not frappe.db.get_value("Region", region, "base_url"):
		doc = frappe.get_doc("Region", region)
		doc.update({"base_url": f"https://{region}.atlas.example.test", "status": "Active", **overrides})
		doc.save(ignore_permissions=True)
	return region
