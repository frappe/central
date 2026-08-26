from __future__ import annotations

import re

import frappe
from frappe import _

from central.services.drivers.garage import GarageDriver
from central.services.provisioning import active_managed_service, get_active_service, get_backend

# One bucket per bench, named by the user. Central owns the mint; a bench only ever
# reaches the S3 gateway, never Garage's admin API.

SERVICE = "storage"
SECRET_LENGTH = 32
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def mint_cluster_tokens(region: str, host: str) -> dict:
	"""The secrets a Garage node needs in its `garage.toml`. Opaque, not signed: Garage
	compares the bearer token it was configured with, it verifies nothing.

	Idempotent per region — every node in a cluster needs the same `rpc_secret`."""
	backend = _cluster_backend(region, host)
	if not backend.get_password("control_api_secret", raise_exception=False):
		backend.control_api_secret = frappe.generate_hash(length=SECRET_LENGTH)
		backend.metrics_token = frappe.generate_hash(length=SECRET_LENGTH)
		backend.rpc_secret = frappe.generate_hash(length=SECRET_LENGTH)
		backend.is_active = 1
		backend.save(ignore_permissions=True)

	return {
		"admin_token": backend.get_password("control_api_secret"),
		"metrics_token": backend.get_password("metrics_token"),
		"rpc_secret": backend.get_password("rpc_secret"),
	}


def enable_bench(pilot_credential: str, bucket: str) -> dict:
	"""Create the bench's bucket under the name it asked for and mint an S3 key scoped to
	it. Idempotent per bench — a re-enable reuses the same bucket and its objects."""
	validate_bucket_name(bucket)
	credential = _existing_credential(pilot_credential)
	if credential and credential.label != bucket:
		# A rename would strand the first bucket's objects behind a dead name.
		frappe.throw(_("This bench already owns the bucket {0}.").format(credential.label))
	if credential and credential.status == "Active":
		return _config(frappe.get_doc("Service Credential", credential.name))

	team = frappe.db.get_value("Pilot Credential", pilot_credential, "team")
	managed_service = active_managed_service(team, SERVICE)
	backend = get_backend(get_active_service(SERVICE).name)

	driver = GarageDriver()
	bucket_id = driver.get_bucket_id(backend, bucket) if credential else None
	key = driver.mint_key(backend, pilot_credential, bucket_id or driver.create_bucket(backend, bucket))

	stored = (
		frappe.get_doc("Service Credential", credential.name)
		if credential
		else frappe.new_doc("Service Credential")
	)
	stored.update(
		{
			"subject_type": "Bench",
			"managed_service": managed_service,
			"pilot_credential": pilot_credential,
			"label": bucket,
			"status": "Active",
			"gateway_url": backend.s3_endpoint,
			"provider_ref": key["access_key_id"],
			"api_key": key["secret_access_key"],
		}
	)
	stored.save()

	return _config(stored)


def disable_bench(pilot_credential: str) -> dict:
	"""Revoke the bench's key at Garage and mark the row revoked. The bucket stays."""
	credential = _existing_credential(pilot_credential)
	if not credential or credential.status != "Active":
		return {"status": "not_enabled"}

	stored = frappe.get_doc("Service Credential", credential.name)
	GarageDriver().revoke_key(get_backend(get_active_service(SERVICE).name), stored.provider_ref)
	stored.db_set("status", "Revoked")

	return {"status": "Revoked"}


def bench_config(pilot_credential: str) -> dict:
	"""The bench's delivered S3 config. Raises when storage was never enabled for it."""
	credential = _existing_credential(pilot_credential)
	if not credential or credential.status != "Active":
		frappe.throw(_("Object storage is not enabled for this bench."))

	return _config(frappe.get_doc("Service Credential", credential.name))


def validate_bucket_name(bucket: str) -> None:
	"""S3 bucket naming, which Garage's global aliases follow: 3-63 characters, lowercase
	letters, digits, dots and hyphens, starting and ending alphanumeric."""
	if not bucket or not BUCKET_NAME_PATTERN.match(bucket):
		frappe.throw(
			_(
				"{0} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			).format(bucket)
		)


def _cluster_backend(region: str, host: str):
	"""One region's Garage cluster row, reserved on first ask. The first host to ask
	stays the entry node Central drives."""
	add_on = get_active_service(SERVICE)
	name = frappe.db.get_value("Service Backend", {"service": add_on.name, "region": region})
	if name:
		return frappe.get_doc("Service Backend", name)

	return frappe.get_doc(
		{
			"doctype": "Service Backend",
			"service": add_on.name,
			"region": region,
			"base_url": f"http://{host}:3903",
			"s3_endpoint": f"http://{host}:3900",
			"is_active": 0,
		}
	).insert(ignore_permissions=True)


def _existing_credential(pilot_credential: str):
	return frappe.db.get_value(
		"Service Credential",
		{"subject_type": "Bench", "pilot_credential": pilot_credential},
		["name", "status", "label"],
		as_dict=True,
	)


def _config(credential) -> dict:
	return {
		"credential": credential.name,
		"endpoint_url": credential.gateway_url,
		"bucket": credential.label,
		"access_key_id": credential.provider_ref,
		"secret_access_key": credential.get_password("api_key"),
		"status": "Active",
	}
