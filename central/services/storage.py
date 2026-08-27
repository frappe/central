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


class BucketProvisioningContext:
	"""Orchestrates multi-step infrastructure calls with LIFO rollback guarantees."""

	def __init__(self, stored_doc: ServiceCredential):
		self.doc = stored_doc
		self.rollbacks: list[tuple[typing.Callable[[], None], str, str]] = []

	def add_rollback(self, action: typing.Callable[[], None], error_title: str, error_msg: str) -> None:
		"""Register a compensating action to run if downstream steps fail."""
		self.rollbacks.append((action, error_title, error_msg))

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_val, exc_tb):
		if exc_type is None:
			return False  # Success: let execution continue normally

		# Failure: execute rollbacks in reverse order (LIFO)
		fully_cleaned = True
		for action, title, message in reversed(self.rollbacks):
			try:
				action()
			except Exception:
				fully_cleaned = False
				frappe.log_error(title=title, message=f"{message}\n\n{frappe.get_traceback()}")

		# Nothing here may raise, or it replaces the error the caller is propagating.
		try:
			self._settle(fully_cleaned)
			self._safe_commit()
		except Exception:
			frappe.log_error(
				title="Could not settle a failed bucket reservation",
				message=f"{self.doc.name} needs reconciling.\n\n{frappe.get_traceback()}",
			)

		return False  # Propagate the original exception

	def _settle(self, fully_cleaned: bool) -> None:
		"""What becomes of the reservation. It survives whenever infrastructure does: as
		Failed when a rollback could not finish, and untouched while it still names a
		bucket an earlier attempt left behind — that row is the bucket's only record, and
		the next attempt adopts it. Only a reservation holding nothing is deleted."""
		if not fully_cleaned:
			self.doc.db_set("status", "Failed", commit=False)
		elif not self.doc.provider_bucket_id:
			self.doc.delete(ignore_permissions=True)

	@staticmethod
	def _safe_commit() -> None:
		if not frappe.in_test:
			frappe.db.commit()


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


def _reserve(managed_service: str, bucket: str, backend: ServiceBackend) -> ServiceCredential:
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

	with BucketProvisioningContext(stored) as ctx:
		# Only a reservation an earlier attempt left behind carries an id, and only by
		# id — never by name, which another team may hold by now.
		adopted = bool(stored.provider_bucket_id) and driver.bucket_exists(
			backend,
			stored.provider_bucket_id,
		)

		if adopted:
			bucket_id = stored.provider_bucket_id
		else:
			bucket_id = driver.create_bucket(backend, bucket)
			stored.db_set("provider_bucket_id", bucket_id, commit=not frappe.in_test)

			def drop_created_bucket() -> None:
				# Clearing the id is part of the rollback: it is what tells the context
				# the reservation no longer names anything.
				driver.delete_bucket(backend, bucket_id)
				stored.db_set("provider_bucket_id", None, commit=False)

			ctx.add_rollback(
				action=drop_created_bucket,
				error_title="Garage bucket left behind after a failed provision",
				error_msg=f"{bucket_id} still exists.",
			)

		key = driver.mint_key(backend, bucket, bucket_id)
		ctx.add_rollback(
			action=lambda: driver.revoke_key(backend, key["access_key_id"]),
			error_title="Garage key left behind after a failed provision",
			error_msg=f"{key['access_key_id']} is still live.",
		)

		stored.update(
			{
				"status": "Active",
				"gateway_url": backend.s3_endpoint,
				"provider_ref": key["access_key_id"],
				"api_key": key["secret_access_key"],
			}
		)
		stored.save()

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


def validate_bucket_name(bucket: str) -> None:
	"""S3 bucket naming, which Garage's global aliases follow."""
	if not bucket or not BUCKET_NAME_PATTERN.match(bucket):
		frappe.throw(
			_(
				f"{bucket} is not a valid bucket name. Use 3-63 characters: lowercase letters, "
				"digits, dots and hyphens, starting and ending with a letter or digit."
			)
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
