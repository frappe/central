from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


# NOTE: Not a web endpoint — a local dev bootstrap run via `pilot frappe execute` (it has no
# role check beyond developer_mode, so it must never be reachable over HTTP).
def setup_local(
	region: str = "in-bengaluru",
	atlas_base_url: str | None = None,
	atlas_region_id: str | None = None,
	seed_demo_data: int = 1,
	check_connection: int = 1,
) -> dict:
	"""One-shot local Central bootstrap.

	This is intentionally developer-mode-only: it creates fake billing/catalog data
	and can check signed access to a configured local Atlas site.
	"""
	_require_developer_mode()

	out: dict = {"developer_mode": True}
	if _truthy(seed_demo_data):
		from central.billing.demo.demo_scenarios import seed_demo, summary

		out["demo_data"] = seed_demo()
		out["summary"] = summary()
	else:
		out["demo_data"] = "skipped"

	if atlas_base_url:
		instance = _upsert_local_atlas_instance(
			region=region,
			base_url=atlas_base_url,
			atlas_region_id=atlas_region_id,
		)
		out["atlas_instance"] = _atlas_result(instance)
		if _truthy(check_connection):
			out["atlas_connection"] = instance.test_connection()
			instance.reload()
			out["atlas_instance"] = _atlas_result(instance)
	else:
		out["atlas_instance"] = "skipped"

	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- command-style local bootstrap persists setup rows.
	return out


def _require_developer_mode() -> None:
	if not cint(frappe.conf.get("developer_mode")):
		frappe.throw(
			_("Local developer setup can only run when developer_mode is enabled."),
			frappe.PermissionError,
		)


def _ensure_region(region: str) -> None:
	"""Atlas Instance.region links Region, so the region must exist first. Local
	dev creates a bare Region (no map metadata); the operator or the demo seed
	fills display_name/provider/coordinates in later."""
	if not frappe.db.exists("Region", region):
		frappe.get_doc({"doctype": "Region", "region": region}).insert(ignore_permissions=True)


def _upsert_local_atlas_instance(
	*,
	region: str,
	base_url: str,
	atlas_region_id: str | None,
):
	_ensure_region(region)
	instance = (
		frappe.get_doc("Atlas Instance", region)
		if frappe.db.exists("Atlas Instance", region)
		else frappe.new_doc("Atlas Instance")
	)
	instance.region = region
	instance.base_url = base_url
	instance.atlas_region_id = atlas_region_id
	instance.status = "Active"
	# This developer-only command creates operator configuration without a web session.
	instance.save(ignore_permissions=True)
	return instance


def _atlas_result(instance) -> dict:
	return {
		"region": instance.region,
		"base_url": instance.base_url,
		"status": instance.status,
		"atlas_region_id": instance.atlas_region_id,
		"reachable": bool(instance.reachable),
	}


def _truthy(value) -> bool:
	return bool(cint(value))
