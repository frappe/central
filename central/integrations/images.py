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


def eligible_plans(team: str, cluster: str, offering: str, image_id: str) -> dict:
	"""Combine billing eligibility with the selected image's disk requirement."""
	from math import ceil

	from central.billing.api.dashboard.catalog import get_eligible_plans
	from central.billing.catalog.composition import DISK, composition_quantities

	image = selected_image(team, cluster, offering, image_id)
	catalog = get_eligible_plans(cluster=cluster, team=team)
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
