# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared fixtures for central tests."""

import frappe


def ensure_region(region: str) -> str:
	"""Create the Region master if it isn't there yet.

	Atlas Instance.region is a required Link to Region, so a test that wants a
	cluster needs the region to exist first.
	"""
	if not frappe.db.exists("Region", region):
		frappe.get_doc({"doctype": "Region", "region": region}).insert(ignore_permissions=True)
	return region


def ensure_atlas_instance(region: str, **overrides) -> str:
	"""Create the cluster a test wants to put resources in (with its Region)."""
	ensure_region(region)
	if not frappe.db.exists("Atlas Instance", region):
		frappe.get_doc(
			{
				"doctype": "Atlas Instance",
				"region": region,
				"base_url": f"https://{region}.atlas.example.test",
				"status": "Active",
				"api_key": "test-key",
				"api_secret": "test-secret",
				**overrides,
			}
		).insert(ignore_permissions=True)
	return region
