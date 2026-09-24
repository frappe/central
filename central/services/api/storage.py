from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType

from central.iam import can, resolve_team
from central.integrations.bucket_provisioning import STORAGE_SERVICE, get_backup_bucket_name
from central.services.doctype.team_service.team_service import TeamService

BUCKET_FIELDS = ("name", "bucket_name", "region", "status", "endpoint_url", "access_key", "creation")


@frappe.whitelist(methods=["GET"])
def get_object_storage(team: str | None = None) -> dict:
	"""The regions that serve object storage and the team's buckets. Gated on `service:view`."""
	team = _authorized_team(team, "service:view")
	# Team Service is operator-only because it holds secrets; this route redacts them.
	buckets = frappe.get_all(
		"Team Service",
		filters={"team": team, "add_on_service": STORAGE_SERVICE},
		fields=list(BUCKET_FIELDS),
		order_by="creation desc",
	)

	return {"regions": get_storage_regions(), "buckets": buckets}


@frappe.whitelist(methods=["POST"])
def create_bucket(team: str | None = None, bucket_name: str | None = None, region: str | None = None) -> dict:
	"""Create a bucket and return its secret once. Gated on `service:manage`."""
	team = _authorized_team(team, "service:manage")
	bucket_name = (bucket_name or "").strip()
	if not bucket_name or not region:
		frappe.throw(_("A bucket needs a name and a region."))

	service = frappe.get_doc(
		{
			"doctype": "Team Service",
			"team": team,
			"add_on_service": STORAGE_SERVICE,
			"region": region,
			"bucket_name": bucket_name,
		}
	)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.insert(ignore_permissions=True)
	return _credentials(service)


@frappe.whitelist(methods=["POST"])
def rotate_credentials(team: str | None = None, name: str | None = None) -> dict:
	"""Replace a bucket's key and return the new secret once. Gated on `service:manage`."""
	service = _customer_bucket(_authorized_team(team, "service:manage"), name)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.flags.ignore_permissions = True
	service.rotate_credentials()
	return _credentials(service)


@frappe.whitelist(methods=["POST"])
def delete_bucket(team: str | None = None, name: str | None = None) -> dict:
	"""Delete an empty bucket and its key. Gated on `service:manage`."""
	service = _customer_bucket(_authorized_team(team, "service:manage"), name)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.delete(ignore_permissions=True)
	return {"name": service.name}


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


def _authorized_team(team: str | None, capability: str) -> str:
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, capability):
		frappe.throw(_("You can't manage this team's object storage."), frappe.PermissionError)
	return team


def _customer_bucket(team: str, name: str | None) -> TeamService:
	"""A bucket this team made. The backup bucket is refused: the team's servers in that
	region write to it with the current key."""
	values = frappe.db.get_value("Team Service", name, ["team", "region", "bucket_name"], as_dict=True)
	if not values or values.team != team:
		frappe.throw(_("No bucket '{0}' for this team.").format(name), frappe.DoesNotExistError)

	if values.bucket_name == get_backup_bucket_name(team, values.region):
		frappe.throw(_("The server backup bucket is managed by Frappe Cloud."))

	return frappe.get_doc("Team Service", name)


def _credentials(service: TeamService) -> dict:
	return {
		"name": service.name,
		"bucket_name": service.bucket_name,
		"region": service.region,
		"endpoint_url": service.endpoint_url,
		"access_key": service.access_key,
		"secret_access_key": service.get_password("secret_access_key"),
	}
