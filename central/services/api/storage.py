import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils.translations import _lt

from central.integrations.object_storage import BucketInteractions
from central.services.doctype.team_service.team_service import STORAGE_SERVICE, TeamService, get_bucket_name
from central.signups.access import require_service_access
from central.utils.guards import require_capability

BUCKET_FIELDS = ("name", "bucket_name", "region", "status", "endpoint_url", "access_key", "creation")
VIEW_DENIED = _lt("You can't view this team's object storage. Ask a team admin to review your access.")
MANAGE_DENIED = _lt("You can't manage this team's object storage. Ask a team admin to review your access.")


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_object_storage(team: str | None = None) -> dict:
	"""The regions that serve object storage and the team's buckets, without secrets."""
	# Team Service is operator-only because it holds secrets; this route redacts them.
	buckets = frappe.get_all(
		"Team Service",
		filters={"team": team, "add_on_service": STORAGE_SERVICE},
		fields=list(BUCKET_FIELDS),
		order_by="creation desc",
	)

	return {"regions": get_storage_regions(), "buckets": buckets}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_bucket_usage(team: str | None = None, name: str | None = None) -> dict:
	"""What one bucket holds, against its caps: `used_bytes`, `object_count`,
	`quota_bytes` and `quota_objects`. A None cap means uncapped."""
	return _team_bucket(team, name).get_usage()


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def list_objects(
	team: str | None = None,
	name: str | None = None,
	prefix: str = "",
	offset: str | None = None,
	limit: int = 100,
) -> dict:
	"""One page of a bucket's objects and folders under `prefix`. Pass `next_offset` back
	as `offset` for the next page."""
	return BucketInteractions(_team_bucket(team, name)).fetch_objects(prefix, offset, limit)


# A download link reads the object's contents, which service:view does not grant.
@frappe.whitelist(methods=["GET"])
@require_capability("service:manage", MANAGE_DENIED)
def get_object_url(team: str | None = None, name: str | None = None, key: str | None = None) -> dict:
	"""A download link for one object that expires in 5 minutes."""
	if not key:
		frappe.throw(_("Choose an object to download."))

	return {"url": BucketInteractions(_team_bucket(team, name)).get_object_url(key)}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def get_upload_url(
	team: str | None = None,
	name: str | None = None,
	key: str | None = None,
	content_type: str | None = None,
) -> dict:
	"""An upload link for one object that expires in 1 hour. PUT the file to it with the
	same Content-Type. An existing object with this key is replaced."""
	_validate_key(key)
	content_type = content_type or "application/octet-stream"

	return {"url": BucketInteractions(_team_bucket(team, name)).get_upload_url(key, content_type)}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def delete_objects(
	team: str | None = None,
	name: str | None = None,
	keys: list[str] | None = None,
	prefixes: list[str] | None = None,
) -> dict:
	"""Delete objects and folders. A folder prefix ends in `/` and takes everything under it.
	Refuses more than 1000 objects in total."""
	keys, prefixes = keys or [], prefixes or []
	if not keys and not prefixes:
		frappe.throw(_("Choose what to delete."))

	for key in keys:
		_validate_key(key)
	for prefix in prefixes:
		_validate_key(prefix)
		if not prefix.endswith("/"):
			frappe.throw(_("A folder must end in '/'."))

	deleted = BucketInteractions(_team_bucket(team, name)).delete_objects(keys, prefixes)
	return {"deleted": deleted}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def create_bucket(team: str | None = None, bucket_name: str | None = None, region: str | None = None) -> dict:
	"""Create a bucket and return its secret once. The bucket is named
	`<tenant>-<region>-<bucket_name>`, because bucket names are shared across a region. Not on a free trial."""
	require_service_access(team)
	bucket_name = (bucket_name or "").strip()
	if not bucket_name or not region:
		frappe.throw(_("A bucket needs a name and a region."))

	service = frappe.get_doc(
		{
			"doctype": "Team Service",
			"team": team,
			"add_on_service": STORAGE_SERVICE,
			"region": region,
			"bucket_name": get_bucket_name(team, region, bucket_name),
		}
	)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.insert(ignore_permissions=True)

	return _credentials(service)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def rotate_credentials(team: str | None = None, name: str | None = None) -> dict:
	"""Replace a bucket's key and return the new secret once. The old key stops at once."""
	service = _team_bucket(team, name, for_update=True)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.flags.ignore_permissions = True
	service.rotate_credentials()

	return _credentials(service)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def delete_bucket(team: str | None = None, name: str | None = None) -> dict:
	"""Delete an empty bucket and its key. Cargo refuses a bucket that still holds objects."""
	service = _team_bucket(team, name, for_update=True)
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
	_team_bucket(team, name, for_update=True).set_quota(size_gib, max_objects)
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
		frappe.throw(
			_(
				"Bucket '{0}' is not available on this team. Return to Object Storage and refresh the bucket list."
			).format(name),
			frappe.DoesNotExistError,
		)

	return frappe.get_doc("Team Service", name, for_update=for_update)


def _validate_key(key: str | None) -> None:
	"""An object key or folder prefix that names something inside the bucket. An empty
	prefix would match the whole bucket."""
	if not key or not isinstance(key, str):
		frappe.throw(_("Choose an object."))
	if key.startswith("/") or ".." in key.split("/") or len(key.encode()) > 1024:
		frappe.throw(
			_(
				"'{0}' is not a valid file or folder name. Use a name of at most 1024 bytes, without a leading slash or a '..' path segment."
			).format(key)
		)


def _credentials(service: TeamService) -> dict:
	return {
		"name": service.name,
		"bucket_name": service.bucket_name,
		"region": service.region,
		"endpoint_url": service.endpoint_url,
		"access_key": service.access_key,
		"secret_access_key": service.get_password("secret_access_key"),
	}
