from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


# NOTE: Not a web endpoint — a local dev bootstrap run via `bench execute` (it has no
# role check beyond developer_mode, so it must never be reachable over HTTP).
def setup_local(
	region: str = "in-bengaluru",
	atlas_base_url: str | None = None,
	atlas_api_key: str | None = None,
	atlas_api_secret: str | None = None,
	seed_demo_data: int = 1,
	register_atlas: int = 1,
) -> dict:
	"""One-shot local Central bootstrap.

	This is intentionally developer-mode-only: it creates fake billing/catalog data
	and can push local Central service credentials to a local Atlas site.
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
			api_key=atlas_api_key,
			api_secret=atlas_api_secret,
		)
		out["atlas_instance"] = _atlas_result(instance)
		if _truthy(register_atlas):
			_require_atlas_credentials(instance)
			out["atlas_registration"] = instance.register()
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
	api_key: str | None,
	api_secret: str | None,
):
	_ensure_region(region)
	if frappe.db.exists("Atlas Instance", region):
		instance = frappe.get_doc("Atlas Instance", region)
	else:
		_require_new_instance_credentials(api_key, api_secret)
		instance = frappe.new_doc("Atlas Instance")
		instance.region = region

	instance.base_url = base_url
	instance.status = "Active"
	instance.skip_tunnel = 1
	if api_key:
		instance.api_key = api_key
	if api_secret:
		instance.api_secret = api_secret
	instance.save(ignore_permissions=True)
	return instance


def _require_new_instance_credentials(api_key: str | None, api_secret: str | None) -> None:
	if api_key and api_secret:
		return
	frappe.throw(
		_("Pass atlas_api_key and atlas_api_secret when creating a new Atlas Instance."),
		frappe.ValidationError,
	)


def _require_atlas_credentials(instance) -> None:
	if instance.api_key and instance.get_password("api_secret", raise_exception=False):
		return
	frappe.throw(
		_("Set atlas_api_key and atlas_api_secret before registering Atlas."),
		frappe.ValidationError,
	)


def _atlas_result(instance) -> dict:
	return {
		"region": instance.region,
		"base_url": instance.base_url,
		"status": instance.status,
		"skip_tunnel": cint(instance.skip_tunnel),
		"tunnel_status": instance.tunnel_status,
		"service_user": instance.service_user,
	}


def _truthy(value) -> bool:
	return bool(cint(value))
