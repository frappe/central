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


def cluster_tokens(backend: ServiceBackend) -> dict:
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
	"""Create a Service Credential document for the bucket, without provisioning it yet."""
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
			"status": "Provisioning",
		}
	)


def _config(credential: ServiceCredential) -> dict:
	return {
		"credential": credential.name,
		"endpoint_url": credential.gateway_url,
		"bucket": credential.label,
		"access_key_id": credential.provider_ref,
		"secret_access_key": credential.get_password("api_key"),
		"status": "Active",
	}


def create_bucket(team: str, bucket: str) -> dict:
	"""Create the team's bucket and mint the key scoped to it. The name goes on last, so a
	failure leaves at most an unnamed, keyless bucket: nothing to find, and nothing holding
	the name against a retry."""
	backend = get_backend(get_active_service(SERVICE).name)
	driver = GarageDriver()
	validate_bucket_name(driver, backend, bucket)

	key = None
	credential = create_service_credential(team, bucket, backend)
	bucket_id = driver.create_bucket(backend)

	try:
		key = driver.mint_key(backend, bucket, bucket_id)
		driver.attach_alias(backend, bucket_id, bucket)
		credential.update(
			{
				"status": "Active",
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


def _discard(driver: GarageDriver, backend: ServiceBackend, bucket_id: str, key: str | None = None) -> None:
	"""Delete the bucket this attempt made, keys and all. Best effort: the cluster that
	refused the provision can refuse this too, and it must not raise over the error being
	propagated. What survives is unnamed, so it blocks nothing."""
	try:
		driver.delete_bucket(backend, bucket_id)
		if key:
			driver.revoke_key(backend, key)
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
