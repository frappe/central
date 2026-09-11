from __future__ import annotations

import re
import typing

import frappe
from frappe import _

from central.integrations.cargo_client import CargoClient
from central.services.provisioning import active_managed_service, get_active_service, get_backend

if typing.TYPE_CHECKING:
	from central.services.doctype.service_backend.service_backend import ServiceBackend
	from central.services.doctype.service_credential.service_credential import ServiceCredential

SERVICE = "storage"
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def validate_bucket_name(bucket: str) -> None:
	"""S3 bucket naming, which Garage's global aliases follow. Whether the name is free is
	Cargo's to answer -- it owns the cluster -- and it refuses a taken one."""
	if not bucket or not BUCKET_NAME_PATTERN.match(bucket):
		frappe.throw(
			_(
				f"{bucket} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			)
		)


def create_service_credential(team: str, bucket: str, backend: ServiceBackend) -> ServiceCredential:
	"""The bucket's row, unsaved and not yet provisioned."""
	managed_service = active_managed_service(team, SERVICE)

	if frappe.db.exists(
		"Service Credential", {"managed_service": managed_service, "label": bucket, "status": "Active"}
	):
		frappe.throw(_(f"You already have a bucket named {bucket}."))

	return frappe.get_doc(
		{
			"doctype": "Service Credential",
			"subject_type": "Team",
			"managed_service": managed_service,
			"service_backend": backend.name,
			"label": bucket,
			"status": "Active",
		}
	)


def endpoint_of(service_backend: str) -> str | None:
	"""Where a bucket is spoken S3 to. One gateway per cluster, so the backend holds it and
	a credential does not carry its own copy to drift."""
	return frappe.db.get_value("Service Backend", service_backend, "service_endpoint")


def _config(credential: ServiceCredential) -> dict:
	return {
		"credential": credential.name,
		"endpoint_url": endpoint_of(credential.service_backend),
		"bucket": credential.label,
		"access_key_id": credential.provider_ref,
		"secret_access_key": credential.get_password("api_key"),
		"status": credential.status,
	}


def create_bucket(team: str, bucket: str) -> dict:
	"""Ask the region's Cargo host for the team's bucket and store the key it hands back.
	Nothing is written until the bucket exists, and a failure takes it back."""
	backend = get_backend(get_active_service(SERVICE).name)
	validate_bucket_name(bucket)

	credential = create_service_credential(team, bucket, backend)
	cargo = CargoClient(backend.region)
	credentials = cargo.create_bucket(bucket)

	try:
		credential.update(
			{
				"provider_ref": credentials["access_key"],
				"api_key": credentials["secret_access_key"],
			}
		).insert()
	except Exception:
		_discard(cargo, bucket)
		raise

	return _config(credential)


def _discard(cargo: CargoClient, bucket: str) -> None:
	"""Take back the bucket this attempt made. Best effort, and never raises over the error
	being propagated. Cargo drops the key along with the bucket, so this is the only call."""
	try:
		cargo.delete_bucket(bucket)
	except Exception:
		frappe.log_error(
			title="Bucket left behind after a failed provision",
			message=f"{bucket} is still live in {cargo.region}.\n\n{frappe.get_traceback()}",
		)


def revoke_bucket(name: str) -> dict:
	"""Revoke a bucket's key at the Cargo host that issued it. The bucket and its objects
	stay."""
	stored = frappe.get_doc("Service Credential", name)
	if stored.status == "Revoked":
		return {"name": name, "status": "Revoked"}
	if not stored.service_backend:
		frappe.throw(_("This credential records no cluster; its key must be revoked at Garage by hand."))

	region = frappe.db.get_value("Service Backend", stored.service_backend, "region")
	CargoClient(region).revoke_credentials(stored.label)
	stored.db_set("status", "Revoked")

	return {"name": name, "status": "Revoked"}
