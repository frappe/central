from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

from central.services.drivers.garage import GarageDriver
from central.services.provisioning import active_managed_service, get_active_service, get_backend

# One bucket per bench, named by the user. Central owns the mint; a bench only ever
# reaches the S3 gateway, never Garage's admin API.

SERVICE = "storage"
SECRET_LENGTH = 32
CLUSTER_SECRETS = ("control_api_secret", "metrics_token", "rpc_secret")
BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def mint_cluster_tokens(region: str, host: str) -> dict:
	"""The secrets a Garage node needs in its `garage.toml`. Opaque, not signed: Garage
	compares the bearer token it was configured with. Idempotent per region — every node
	in a cluster needs the same `rpc_secret`, and the first host to ask stays the entry
	node Central drives."""
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
	"""One cluster's secrets, generated on first ask and returned unchanged after. Filled
	in per field so a partially configured row completes rather than throws."""
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


def enable_bench(pilot_credential: str, bucket: str) -> dict:
	"""Create the bench's bucket under the name it asked for and mint an S3 key scoped to
	it. Idempotent per bench — a re-enable reuses the same bucket and its objects."""
	validate_bucket_name(bucket)
	credential = _existing_credential(pilot_credential)
	if credential and credential.label != bucket:
		frappe.throw(_(f"This bench already owns the bucket {credential.label}."))
	if credential and credential.status == "Active":
		return _config(frappe.get_doc("Service Credential", credential.name))

	# The cluster that holds this bench's bucket, not whichever backend is active now: a
	# key can only be minted or revoked at the Garage that owns the bucket.
	backend = (
		frappe.get_doc("Service Backend", credential.service_backend)
		if credential and credential.service_backend
		else get_backend(get_active_service(SERVICE).name)
	)

	stored = _reserve(credential, pilot_credential, bucket, backend)
	driver = GarageDriver()
	known_bucket_id = credential.provider_bucket_id if credential else None
	fresh_bucket_id = None
	key = None

	try:
		if known_bucket_id and not driver.bucket_exists(backend, known_bucket_id):
			frappe.throw(_(f"Bucket {bucket} no longer exists on this cluster."))
		if not known_bucket_id:
			# Recorded straight away: a retry adopts by id alone, since re-resolving the
			# name could land on a bucket another tenant claimed since.
			fresh_bucket_id = driver.create_bucket(backend, bucket)
			stored.db_set("provider_bucket_id", fresh_bucket_id, commit=not frappe.in_test)

		key = driver.mint_key(backend, pilot_credential, known_bucket_id or fresh_bucket_id)
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
		_discard(driver, backend, stored, key, fresh_bucket_id)
		raise

	return _config(stored)


def _discard(
	driver: GarageDriver, backend: Document, stored: Document, key: dict | None, fresh_bucket_id: str | None
) -> None:
	"""Undo a half-finished provision. Only a bucket this attempt created is passed here;
	one carried over from an earlier attempt may hold objects.

	Every step is attempted and none may raise — one failed cleanup must not skip the
	next, and none of them may replace the provisioning error the caller is about to
	re-raise. What could not be undone is logged for an operator to reconcile."""
	if key:
		try:
			driver.revoke_key(backend, key["access_key_id"])
		except Exception:
			frappe.log_error(
				title="Garage key left behind after a failed provision",
				message=f"{key['access_key_id']} is still live.",
			)

	if fresh_bucket_id:
		try:
			driver.delete_bucket(backend, fresh_bucket_id)
			stored.db_set("provider_bucket_id", None, commit=not frappe.in_test)
		except Exception:
			frappe.log_error(
				title="Garage bucket left behind after a failed provision",
				message=f"{fresh_bucket_id} still exists.",
			)


def _reserve(credential, pilot_credential: str, bucket: str, backend: Document) -> Document:
	"""Record the bucket and its cluster before Garage is touched, once the team's
	entitlement is confirmed. The row must survive a failure mid-provision: without it the
	bucket is untracked, and the next attempt cannot tell its own orphan from another
	tenant's. (Skipped under tests, where the row stays visible in the test transaction.)"""
	team = frappe.db.get_value("Pilot Credential", pilot_credential, "team")
	managed_service = active_managed_service(team, SERVICE)
	stored = (
		frappe.get_doc("Service Credential", credential.name)
		if credential
		else frappe.new_doc("Service Credential")
	)
	stored.update(
		{
			"subject_type": "Bench",
			"managed_service": managed_service,
			"service_backend": backend.name,
			"pilot_credential": pilot_credential,
			"label": bucket,
			"status": "Provisioning",
		}
	)
	stored.save()
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- record of intent, see docstring

	return stored


def disable_bench(pilot_credential: str) -> dict:
	"""Revoke the bench's key at Garage and mark the row revoked. The bucket stays."""
	credential = _existing_credential(pilot_credential)
	if not credential or credential.status != "Active":
		return {"status": "not_enabled"}

	stored = frappe.get_doc("Service Credential", credential.name)
	if not stored.service_backend:
		frappe.throw(_("This credential records no cluster; its key must be revoked at Garage by hand."))

	GarageDriver().revoke_key(frappe.get_doc("Service Backend", stored.service_backend), stored.provider_ref)
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
				f"{bucket} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			)
		)


def _existing_credential(pilot_credential: str) -> frappe._dict | None:
	return frappe.db.get_value(
		"Service Credential",
		{"subject_type": "Bench", "pilot_credential": pilot_credential},
		["name", "status", "label", "service_backend", "provider_bucket_id"],
		as_dict=True,
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
