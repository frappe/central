from __future__ import annotations

import frappe

from central.services.permissions import assert_operator


def register_backend(service: str, base_url: str, bootstrap_secret: str, region: str | None = None) -> dict:
	"""Register (or re-enroll) an executor deployment for a service. CLI/ops helper —
	deliberately NOT a web endpoint, so the bootstrap secret stays a plain argument and
	is never logged. Operators use the Service Backend "Enroll" button in Desk instead."""
	assert_operator()

	backend = _get_or_create_backend(service, base_url, region)
	backend.apply_control_credential(bootstrap_secret)

	return {"backend": backend.name, "service": service, "is_active": backend.is_active}


def _get_or_create_backend(service: str, base_url: str, region: str | None):
	# region is half of the (service, region) identity; normalise None to "" so the
	# lookup matches the stored value (the controller stores "" too) — otherwise
	# NULL <> "" in MariaDB makes every re-register insert a fresh duplicate row.
	region = region or ""
	name = frappe.db.get_value("Service Backend", {"service": service, "region": region}, "name")
	if name:
		backend = frappe.get_doc("Service Backend", name)
		backend.base_url = base_url
		return backend

	return frappe.get_doc(
		{"doctype": "Service Backend", "service": service, "base_url": base_url, "region": region}
	).insert()
