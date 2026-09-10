from __future__ import annotations

import re
import typing

import frappe
from frappe import _

from central.services.drivers.garage import GarageDriver
from central.services.provisioning import active_managed_service, get_active_service, get_backend

if typing.TYPE_CHECKING:
	from central.services.doctype.service_backend.service_backend import ServiceBackend
	from central.services.doctype.service_credential.service_credential import ServiceCredential

SERVICE = "storage"
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def record_cluster_status(
	region: str,
	is_active: bool,
	base_url: str = "",
	s3_endpoint: str = "",
	web_endpoint: str = "",
	control_api_secret: str = "",
) -> dict:
	"""Record where a region's cluster runs, and whether Central may use it.

	The first report is what creates the backend: Cargo mints the cluster's secrets, so
	Central learns a region exists only when its cluster reports in. A failing cluster
	sends no endpoints and keeps the ones it last had."""
	backend = get_or_create_backend(region)
	backend.is_active = int(is_active)
	if is_active:
		backend.update(
			{
				"base_url": base_url,
				"s3_endpoint": s3_endpoint,
				"web_endpoint": web_endpoint,
				"control_api_secret": control_api_secret,
			}
		)
	backend.save(ignore_permissions=True)

	return {"backend": backend.name, "region": region, "is_active": backend.is_active}


def get_or_create_backend(region: str) -> ServiceBackend:
	"""The region's storage backend, created inactive on its first report."""
	service = get_active_service(SERVICE).name
	name = frappe.db.get_value("Service Backend", {"service": service, "region": region})
	if name:
		return frappe.get_doc("Service Backend", name)

	return frappe.get_doc(
		{"doctype": "Service Backend", "service": service, "region": region, "is_active": 0}
	).insert(ignore_permissions=True)


def validate_bucket_name(driver: GarageDriver, backend: ServiceBackend, bucket: str) -> None:
	"""S3 bucket naming, which Garage's global aliases follow."""
	if not bucket or not BUCKET_NAME_PATTERN.match(bucket):
		frappe.throw(
			_(
				f"{bucket} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			)
		)

	if driver.get_bucket_id(backend, bucket):
		frappe.throw(
			_("The bucket name {0} is already taken. Pick another.").format(bucket),
			title=_("Bucket name taken"),
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


def _config(credential: ServiceCredential) -> dict:
	return {
		"credential": credential.name,
		"endpoint_url": credential.gateway_url,
		"bucket": credential.label,
		"access_key_id": credential.provider_ref,
		"secret_access_key": credential.get_password("api_key"),
		"status": credential.status,
	}


def create_bucket(team: str, bucket: str) -> dict:
	"""Create the team's bucket and mint the key scoped to it. Nothing is written until
	the bucket works, and a failure takes back whatever this attempt made."""
	driver = GarageDriver()
	backend = get_backend(get_active_service(SERVICE).name)
	validate_bucket_name(driver, backend, bucket)

	key = None
	credential = create_service_credential(team, bucket, backend)
	bucket_id = driver.create_bucket(backend)

	try:
		key = driver.mint_key(backend, bucket, bucket_id)
		driver.attach_alias(backend, bucket_id, bucket)
		credential.update(
			{
				"gateway_url": backend.s3_endpoint,
				"provider_bucket_id": bucket_id,
				"provider_ref": key["access_key_id"],
				"api_key": key["secret_access_key"],
			}
		).insert()
	except Exception:
		_discard(driver, backend, bucket_id, key)
		raise

	return _config(credential)


def _discard(driver: GarageDriver, backend: ServiceBackend, bucket_id: str, key: dict | None = None) -> None:
	"""Take back what this attempt made, each on its own so one failure does not skip the
	other. Best effort, and never raises over the error being propagated. The key needs its
	own call: deleting a bucket does not revoke keys allowed on it."""
	if key:
		try:
			driver.revoke_key(backend, key["access_key_id"])
		except Exception:
			frappe.log_error(
				title="Garage key left behind after a failed provision",
				message=f"{key['access_key_id']} is still live.\n\n{frappe.get_traceback()}",
			)

	try:
		driver.delete_bucket(backend, bucket_id)
	except Exception:
		frappe.log_error(
			title="Garage bucket left behind after a failed provision",
			message=f"Unnamed bucket {bucket_id}.\n\n{frappe.get_traceback()}",
		)


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
