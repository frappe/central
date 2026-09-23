from __future__ import annotations

import frappe
from frappe import _

from central.iam import can
from central.integrations.atlas import AtlasClient


def list_offerings(team: str, flow: str = "Server") -> list[dict]:
	"""List customer image choices.

	1. Require server view access.
	2. Return enabled offerings for the requested flow.
	"""
	validate_catalog_access(team, flow)
	return frappe.get_list(
		"Image Offering",
		filters={"enabled": 1, "available_in": ["in", [flow, "Both"]]},
		fields=["name", "title", "logo", "description", "available_in"],
		order_by="title asc",
		limit=0,
	)


def list_images(
	team: str,
	atlas_instance: str,
	offering: str,
	flow: str = "Server",
	offset: int = 0,
	extra_tags: dict[str, str] | None = None,
) -> dict:
	"""Read a shared catalog under the caller's authorized Team context.

	`extra_tags` narrows the offering selector for one flow, such as the site and the Frappe
	version a trial needs. It comes from Central, never from the request."""
	validate_catalog_access(team, flow)
	document = frappe.get_doc("Image Offering", offering)
	document.check_permission("read")
	if not document.enabled or document.available_in not in (flow, "Both"):
		frappe.throw(_("This image offering is not available for this flow."))

	instance = frappe.get_doc("Region", atlas_instance)
	if instance.status != "Active":
		frappe.throw(_("This region is not accepting new servers."))

	client = AtlasClient.for_team(instance, team)
	return client.list_system_images({**document.get_image_tags(), **(extra_tags or {})}, offset)


def preview_images(offering: str, atlas_instance: str, offset: int = 0) -> dict:
	"""Check an operator's saved selector without creating a regional resource."""
	instance = frappe.get_doc("Region", atlas_instance)
	client = AtlasClient.for_operator(instance)
	document = frappe.get_doc("Image Offering", offering)
	document.check_permission("write")
	return client.list_system_images(document.get_image_tags(), offset)


def validate_catalog_access(team: str, flow: str) -> None:
	"""Validate discovery access.

	1. Require server view capability in the Team.
	2. Accept known creation flows only.
	"""
	if not can(frappe.session.user, team, "server:view"):
		frappe.throw(_("You cannot view servers for this Team."), frappe.PermissionError)

	if flow not in ("Server", "Signup"):
		frappe.throw(_("Select the Server or Signup image flow."))


def selected_image(
	team: str, region: str, offering: str, image_id: str, capability: str = "server:view"
) -> dict:
	"""Resolve a saved offering against the current regional build."""
	document = frappe.get_doc("Image Offering", offering)
	document.check_permission("read")
	if not document.enabled or document.available_in not in ("Server", "Both"):
		frappe.throw(_("This offering is not available for server creation."))

	instance = frappe.get_doc("Region", region)
	if instance.status != "Active":
		frappe.throw(_("This region is not accepting new servers."))

	client = AtlasClient.for_team(instance, team, capability)
	image = client.read_system_image(client.get_image(image_id), document.get_image_tags())
	if not image["enabled"] or image["status"] != "available":
		frappe.throw(_("This image is no longer available. Select another image."))

	return image


def snapshot_source(team: str, snapshot: str) -> tuple[str, str]:
	"""The offering and Atlas image a team's snapshot restores from."""
	row = _restorable_snapshot(team, snapshot)
	return row.image_offering, row.atlas_image_id


def snapshot_image(team: str, region: str, snapshot: str, capability: str = "server:view") -> dict:
	"""Resolve a team's snapshot into the image a new server boots from, in the shape
	`selected_image` returns. Its tags are the source offering's, so the new server is of
	the same kind."""
	row = _restorable_snapshot(team, snapshot)
	if row.region != region:
		frappe.throw(_("A snapshot restores only in the region it was taken in."))

	instance = frappe.get_doc("Region", region)
	if instance.status != "Active":
		frappe.throw(_("This region is not accepting new servers."))

	image = AtlasClient.for_team(instance, team, capability).get_machine_image(row.atlas_image_id)
	if not image.get("enabled") or image.get("status") != "available":
		frappe.throw(_("This snapshot is no longer available in its region."))

	return {
		**{field: image.get(field) for field in ("id", "title", "architecture", "status", "created_at")},
		"enabled": True,
		"rootfs_size_mib": image.get("rootfs_size_mib") or 0,
		"tags": frappe.get_cached_doc("Image Offering", row.image_offering).get_image_tags(),
	}


def _restorable_snapshot(team: str, snapshot: str):
	"""1. Require server:snapshot in the team.
	2. The snapshot must belong to the team, be Available, and not come from a Pilot server."""
	if not can(frappe.session.user, team, "server:snapshot"):
		frappe.throw(_("You cannot restore snapshots for this Team."), frappe.PermissionError)

	row = frappe.db.get_value(
		"VM Snapshot",
		snapshot,
		["team", "region", "status", "atlas_image_id", "image_offering", "is_restorable"],
		as_dict=True,
	)
	if not row or row.team != team:
		frappe.throw(_("No snapshot '{0}' for this team.").format(snapshot), frappe.DoesNotExistError)
	if row.status != "Available":
		frappe.throw(_("Only an available snapshot can be restored."))
	if not row.is_restorable or not row.image_offering:
		frappe.throw(_("A snapshot of a Pilot server cannot be restored yet."))
	return row


def eligible_plans(
	team: str, cluster: str, offering: str, image_id: str, snapshot: str | None = None
) -> dict:
	"""Combine billing eligibility with the selected image's disk requirement. A restore
	passes `snapshot` instead of an offering and image."""
	from math import ceil

	from central.billing.catalog.composition import DISK, composition_quantities
	from central.billing.catalog.server_plans import get_server_plans

	image = (
		snapshot_image(team, cluster, snapshot)
		if snapshot
		else selected_image(team, cluster, offering, image_id)
	)
	catalog = get_server_plans(team, cluster=cluster)
	minimum_disk = image["rootfs_size_mib"]
	groups = {}
	for name, plans in catalog["plans"].items():
		rows = [
			plan
			for plan in plans
			if composition_quantities(plan["includes"]).get(DISK, 0) * 1024 >= minimum_disk
		]
		if rows:
			groups[name] = rows

	profiles = []
	for profile in catalog["profiles"]:
		steps = [size for size in profile["disk_steps"] if size * 1024 >= minimum_disk]
		if steps:
			profiles.append(
				{
					**profile,
					"disk_steps": steps,
					"disk_min": max(profile["disk_min"], ceil(minimum_disk / 1024)),
				}
			)

	return {**catalog, "plans": groups, "profiles": profiles, "image_id": image_id}
