from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.services.drivers.garage import GarageDriver
from central.services.provisioning import active_managed_service, get_active_service, get_backend

SERVICE = "storage"
SECRET_LENGTH = 32
CLUSTER_SECRETS = ("control_api_secret", "metrics_token", "rpc_secret")
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def mint_cluster_tokens(region: str, host: str) -> dict:
	"""A node's `garage.toml` secrets. Idempotent per region: every node in a cluster
	needs the same `rpc_secret`, and the first host to ask stays the entry node."""
	add_on = get_active_service(SERVICE)
	name = frappe.db.get_value("Service Backend", {"service": add_on.name, "region": region})
	backend = (
		frappe.get_doc("Service Backend", name)
		if name
		else frappe.get_doc(
			{
				"doctype": "Service Backend",
				"service": add_on.name,
				"region": region,
				"base_url": f"http://{host}:3903",
				"s3_endpoint": f"http://{host}:3900",
				"is_active": 0,
			}
		).insert(ignore_permissions=True)
	)

	return cluster_tokens(backend)


def cluster_tokens(backend: Document) -> dict:
	"""Generated on first ask, unchanged after. Per field, so a partly configured row
	completes rather than throws."""
	missing = [f for f in CLUSTER_SECRETS if not backend.get_password(f, raise_exception=False)]
	if missing:
		for fieldname in missing:
			backend.set(fieldname, frappe.generate_hash(length=SECRET_LENGTH))
		backend.is_active = 1
		backend.save(ignore_permissions=True)

	return {
		"admin_token": backend.get_password("control_api_secret"),
		"metrics_token": backend.get_password("metrics_token"),
		"rpc_secret": backend.get_password("rpc_secret"),
	}


def create_bucket(team: str, bucket: str) -> dict:
	"""Create the team's bucket and mint the key scoped to it."""
	validate_bucket_name(bucket)
	managed_service = active_managed_service(team, SERVICE)
	if frappe.db.exists(
		"Service Credential", {"managed_service": managed_service, "label": bucket, "status": "Active"}
	):
		frappe.throw(_(f"You already have a bucket named {bucket}."))

	backend = get_backend(get_active_service(SERVICE).name)
	stored = _reserve(managed_service, bucket, backend)
	driver = GarageDriver()
	bucket_id = None
	key = None

	try:
		bucket_id = driver.create_bucket(backend, bucket)
		stored.db_set("provider_bucket_id", bucket_id, commit=not frappe.in_test)
		key = driver.mint_key(backend, bucket, bucket_id)
		stored.update(
			{
				"status": "Active",
				"gateway_url": backend.s3_endpoint,
				"provider_ref": key["access_key_id"],
				"api_key": key["secret_access_key"],
			}
		)
		stored.save()
	except Exception:
		_discard(driver, backend, stored, key, bucket_id)
		raise

	return _config(stored)


def revoke_bucket(name: str) -> dict:
	"""Revoke a bucket's key at the cluster that issued it. The bucket and its objects
	stay."""
	stored = frappe.get_doc("Service Credential", name)
	if stored.status == "Revoked":
		return {"name": name, "status": "Revoked"}
	if not stored.service_backend:
		frappe.throw(_("This credential records no cluster; its key must be revoked at Garage by hand."))

	GarageDriver().revoke_key(frappe.get_doc("Service Backend", stored.service_backend), stored.provider_ref)
	stored.db_set("status", "Revoked")

	return {"name": name, "status": "Revoked"}


def _reserve(managed_service: str, bucket: str, backend: Document) -> Document:
	"""Record the bucket and its cluster before Garage is touched. The row must survive a
	failure mid-create: without it the bucket is untracked, and nothing can tell Central's
	own orphan from another tenant's. (Skipped under tests, where the row stays visible in
	the test transaction.)"""

	abandoned = frappe.db.get_value(
		"Service Credential",
		{"managed_service": managed_service, "label": bucket, "status": "Provisioning"},
		"name",
	)
	stored = (
		frappe.get_doc("Service Credential", abandoned) if abandoned else frappe.new_doc("Service Credential")
	)
	stored.update(
		{
			"subject_type": "Team",
			"managed_service": managed_service,
			"service_backend": backend.name,
			"label": bucket,
			"status": "Provisioning",
		}
	)
	stored.save()
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- record of intent, see docstring

	return stored


def _discard(
	driver: GarageDriver, backend: Document, stored: Document, key: dict | None, bucket_id: str | None
) -> None:
	"""Undo a half-finished create. Nothing here may raise: a failed cleanup must not skip
	the next, nor replace the error the caller is re-raising. The row goes only when Garage
	is provably clean; otherwise it stays as Failed, the only record of what leaked."""
	discarded = True

	if key:
		try:
			driver.revoke_key(backend, key["access_key_id"])
		except Exception:
			discarded = False
			frappe.log_error(
				title="Garage key left behind after a failed provision",
				message=f"{key['access_key_id']} is still live.",
			)

	if bucket_id:
		try:
			driver.delete_bucket(backend, bucket_id)
		except Exception:
			discarded = False
			frappe.log_error(
				title="Garage bucket left behind after a failed provision",
				message=f"{bucket_id} still exists.",
			)

	if not discarded:
		stored.db_set("status", "Failed", commit=not frappe.in_test)
		return

	stored.delete(ignore_permissions=True)
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- undo the committed reservation


def validate_bucket_name(bucket: str) -> None:
	"""S3 bucket naming, which Garage's global aliases follow."""
	if not bucket or not BUCKET_NAME_PATTERN.match(bucket):
		frappe.throw(
			_(
				f"{bucket} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			)
		)


def _config(credential: Document) -> dict:
	return {
		"credential": credential.name,
		"endpoint_url": credential.gateway_url,
		"bucket": credential.label,
		"access_key_id": credential.provider_ref,
		"secret_access_key": credential.get_password("api_key"),
		"status": "Active",
	}
