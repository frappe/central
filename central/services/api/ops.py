from __future__ import annotations

import frappe

from central.services.permissions import assert_operator


@frappe.whitelist()
def register_backend(service: str, base_url: str, bootstrap_secret: str, region: str | None = None) -> dict:
	"""Register (or re-enroll) an executor deployment for a service. Creates the
	Service Backend if needed, then enrolls to mint and store its control credential.
	Operator-only; the bootstrap secret is never persisted."""
	assert_operator()

	backend = _get_or_create_backend(service, base_url, region)
	backend.enroll(bootstrap_secret)

	return {"backend": backend.name, "service": service, "is_active": backend.is_active}


def _get_or_create_backend(service: str, base_url: str, region: str | None):
	name = frappe.db.get_value("Service Backend", {"service": service, "region": region or ""}, "name")
	if name:
		backend = frappe.get_doc("Service Backend", name)
		backend.base_url = base_url
		return backend

	return frappe.get_doc(
		{"doctype": "Service Backend", "service": service, "base_url": base_url, "region": region}
	).insert()
