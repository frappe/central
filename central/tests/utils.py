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


def ensure_server(resource_id: str, team: str, region: str = "scope-test", **fields) -> str:
	"""A Running server of `team`, recreated so each test starts from the same row."""
	ensure_atlas_instance(region)
	if frappe.db.exists("Virtual Machine", resource_id):
		frappe.delete_doc("Virtual Machine", resource_id, force=True, ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Virtual Machine",
			"resource_id": resource_id,
			"team": team,
			"region": region,
			"status": "Running",
			**fields,
		}
	).insert(ignore_permissions=True)
	return resource_id
