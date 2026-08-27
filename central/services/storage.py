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
STALE_PROVISION_MINUTES = 10


def mint_cluster_tokens(region: str, host: str) -> dict:
	"""A node's `garage.toml` secrets. Idempotent per region: a cluster shares one
	`rpc_secret`, and the first host to ask stays the entry node."""
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
	completes."""
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
		"status": credential.status,
	}


def create_bucket(team: str, bucket: str) -> dict:
	"""Create the team's bucket and mint the key scoped to it. The name goes on last, and
	only once the record is on disk, so a failure leaves at most an unnamed, keyless
	bucket: unreachable, and holding no name against a retry."""
	driver = GarageDriver()
	backend = get_backend(get_active_service(SERVICE).name)
	validate_bucket_name(driver, backend, bucket)

	key = None
	credential = create_service_credential(team, bucket, backend)
	bucket_id = driver.create_bucket(backend)

	try:
		key = driver.mint_key(backend, bucket, bucket_id)
		credential.update(
			{
				"gateway_url": backend.s3_endpoint,
				"provider_bucket_id": bucket_id,
				"provider_ref": key["access_key_id"],
				"api_key": key["secret_access_key"],
			}
		).insert()

		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- see above

		driver.attach_alias(backend, bucket_id, bucket)
		credential.db_set("status", "Active")
	except Exception:
		_discard(driver, backend, bucket_id, key, credential)
		raise

	return _config(credential)


def _discard(
	driver: GarageDriver,
	backend: ServiceBackend,
	bucket_id: str,
	key: str | None = None,
	credential: ServiceCredential | None = None,
) -> None:
	"""Delete the bucket this attempt made, keys and all, and the row if it was committed.
	Best effort, and never raises over the error being propagated."""
	try:
		driver.delete_bucket(backend, bucket_id)
		if key:
			driver.revoke_key(backend, key)
	except Exception:
		frappe.log_error(
			title="Garage bucket left behind after a failed provision",
			message=f"Unnamed bucket {bucket_id}.\n\n{frappe.get_traceback()}",
		)

	if not credential or not credential.name or not frappe.db.exists("Service Credential", credential.name):
		return

	try:
		credential.delete(ignore_permissions=True)
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- undo the committed row
	except Exception:
		frappe.log_error(
			title="Bucket record left behind after a failed provision",
			message=f"{credential.name} names a deleted bucket.\n\n{frappe.get_traceback()}",
		)


def sweep_stale_provisioning(minutes: int = STALE_PROVISION_MINUTES) -> int:
	"""Clear buckets a lost worker left half-made, and the rows naming them. A Provisioning
	row never got its alias, so its bucket was never addressable and cannot hold an
	object — deleting it can lose nothing."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes)
	stale = frappe.get_all(
		"Service Credential",
		filters={"subject_type": "Team", "status": "Provisioning", "modified": ["<", cutoff]},
		fields=["name", "provider_bucket_id", "service_backend"],
	)

	swept = 0
	for row in stale:
		try:
			if row.provider_bucket_id and row.service_backend:
				backend = frappe.get_doc("Service Backend", row.service_backend)
				GarageDriver().delete_bucket(backend, row.provider_bucket_id)

			frappe.delete_doc("Service Credential", row.name, force=True, ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one row at a time
			swept += 1
		except Exception:
			frappe.log_error(
				title="Could not sweep a half-made bucket",
				message=f"{row.name} names bucket {row.provider_bucket_id}.\n\n{frappe.get_traceback()}",
			)

	return swept


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
