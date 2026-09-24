from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType

from central.integrations.bucket_provisioning import (
	STORAGE_SERVICE,
	get_backup_bucket_name,
	get_customer_bucket_name,
)
from central.services.doctype.team_service.team_service import TeamService
from central.utils.guards import require_capability

BUCKET_FIELDS = ("name", "bucket_name", "region", "status", "endpoint_url", "access_key", "creation")
VIEW_DENIED = "You can't view this team's object storage."
MANAGE_DENIED = "You can't manage this team's object storage."


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_object_storage(team: str | None = None) -> dict:
	"""The regions that serve object storage and the team's buckets, without secrets.
	`is_managed` marks a server backup bucket, which the team cannot rotate or delete."""
	# Team Service is operator-only because it holds secrets; this route redacts them.
	buckets = frappe.get_all(
		"Team Service",
		filters={"team": team, "add_on_service": STORAGE_SERVICE},
		fields=list(BUCKET_FIELDS),
		order_by="creation desc",
	)

	backup_names = {get_backup_bucket_name(team, region) for region in {bucket.region for bucket in buckets}}
	for bucket in buckets:
		bucket.is_managed = bucket.bucket_name in backup_names

	return {"regions": get_storage_regions(), "buckets": buckets}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_bucket_usage(team: str | None = None, name: str | None = None) -> dict:
	"""What one bucket holds, against its caps: `used_bytes`, `object_count`,
	`quota_bytes` and `quota_objects`. A None cap means uncapped."""
	return _team_bucket(team, name).get_usage()


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def create_bucket(team: str | None = None, bucket_name: str | None = None, region: str | None = None) -> dict:
	"""Create a bucket and return its secret once. The bucket is named
	`<tenant>-<region>-<bucket_name>`, because bucket names are shared across a region."""
	bucket_name = (bucket_name or "").strip()
	if not bucket_name or not region:
		frappe.throw(_("A bucket needs a name and a region."))

	service = frappe.get_doc(
		{
			"doctype": "Team Service",
			"team": team,
			"add_on_service": STORAGE_SERVICE,
			"region": region,
			"bucket_name": get_customer_bucket_name(team, region, bucket_name),
		}
	)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.insert(ignore_permissions=True)
	return _credentials(service)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def rotate_credentials(team: str | None = None, name: str | None = None) -> dict:
	"""Replace a bucket's key and return the new secret once. The old key stops at once."""
	service = _customer_bucket(team, name)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.flags.ignore_permissions = True
	service.rotate_credentials()
	return _credentials(service)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def delete_bucket(team: str | None = None, name: str | None = None) -> dict:
	"""Delete an empty bucket and its key. Cargo refuses a bucket that still holds objects."""
	service = _customer_bucket(team, name)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.delete(ignore_permissions=True)
	return {"name": service.name}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def set_bucket_quota(
	team: str | None = None, name: str | None = None, size_gib: int = 0, max_objects: int = 0
) -> dict:
	"""Cap a bucket's total size in GiB and its object count. Zero lifts a cap. Read the
	caps back from `get_bucket_usage`."""
	_customer_bucket(team, name).set_quota(size_gib, max_objects)
	return {"name": name, "size_gib": size_gib, "max_objects": max_objects}


def get_storage_regions() -> list[dict]:
	"""Regions where Cargo reports object storage as available, with what the map needs."""
	detail = DocType("Service Detail")
	region = DocType("Region")
	return (
		frappe.qb.from_(detail)
		.join(region)
		.on(region.name == detail.region)
		.select(
			region.name.as_("region"),
			region.display_name,
			region.provider,
			region.country_code,
			region.latitude,
			region.longitude,
		)
		.where((detail.service == STORAGE_SERVICE) & (detail.status == "Available"))
		.orderby(region.display_name)
		.run(as_dict=True)
	)


def _team_bucket(team: str, name: str | None, for_update: bool = False) -> TeamService:
	"""One of this team's buckets. `for_update` holds the row, so two rotations cannot
	each save a key the other has already replaced."""
	filters = {"name": name, "team": team, "add_on_service": STORAGE_SERVICE}
	if not name or not frappe.db.exists("Team Service", filters):
		frappe.throw(_("No bucket '{0}' for this team.").format(name), frappe.DoesNotExistError)

	return frappe.get_doc("Team Service", name, for_update=for_update)


def _customer_bucket(team: str, name: str | None) -> TeamService:
	"""A bucket this team may change. The backup bucket is refused: the team's servers in
	that region write to it with the current key."""
	service = _team_bucket(team, name, for_update=True)
	if service.is_backup_bucket():
		frappe.throw(_("The server backup bucket is managed by Frappe Cloud."))

	return service


def _credentials(service: TeamService) -> dict:
	return {
		"name": service.name,
		"bucket_name": service.bucket_name,
		"region": service.region,
		"endpoint_url": service.endpoint_url,
		"access_key": service.access_key,
		"secret_access_key": service.get_password("secret_access_key"),
	}
