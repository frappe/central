# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared fixtures for central tests."""

from contextlib import contextmanager

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


# A 1x1 transparent PNG.
TEST_PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
	"1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def upload_test_image(doctype: str, name: str, fieldname: str) -> str:
	"""Attach a small public image to a document field, as upload_file would, and return its URL."""
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"test-{frappe.generate_hash(length=8)}.png",
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": fieldname,
			"is_private": 0,
			# Unique bytes: Frappe reuses the URL of any File with the same content.
			"content": TEST_PNG + frappe.generate_hash().encode(),
		}
	).insert()
	return file.file_url


@contextmanager
def central_limit(fieldname: str, value: int):
	"""Set one Central Settings limit for the block, then put the old value back."""
	previous = frappe.db.get_single_value("Central Settings", fieldname)
	frappe.db.set_single_value("Central Settings", fieldname, value)
	frappe.clear_document_cache("Central Settings", "Central Settings")
	try:
		yield
	finally:
		frappe.db.set_single_value("Central Settings", fieldname, previous)
		frappe.clear_document_cache("Central Settings", "Central Settings")
