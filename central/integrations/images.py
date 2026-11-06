from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import validate_email_address
from frappe.utils.password_strength import test_password_strength

from central.iam import can
from central.infrastructure.doctype.blocked_domain.blocked_domain import BlockedDomain
from central.infrastructure.doctype.region.region import Region
from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES
from central.integrations.atlas import AtlasClient
from central.integrations.cargo import CargoClient
from central.server_models import DNS_LABEL, AppAnswers, AppInput, AppRequirements
from central.utils.units import MIB_PER_GIB, MILLICORES_PER_VCPU

# The Atlas `purpose` tag of an image a region's Cargo built for an app.
APP_PURPOSE = "one-click"
# The app input whose answer Central routes to the app server, as <answer>.<region zone>.
SITE_NAME_INPUT = "site_name"
# Each answer becomes a shell variable in the app server's inputs.env, so its name must be one.
APP_INPUT_NAME = re.compile(r"[a-z][a-z0-9_]*")
DOMAIN = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


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
		order_by="display_order asc, title asc",
		limit=0,
	)


def list_images(
	team: str,
	region: str,
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

	instance = frappe.get_doc("Region", region)
	instance.ensure_accepts_new_servers()

	client = AtlasClient.for_team(instance, team)

	return client.list_system_images({**document.get_image_tags(), **(extra_tags or {})}, offset)


def list_apps(team: str, region: str) -> list[dict]:
	"""The ready-to-run apps the region's Cargo has built, one per application."""
	return _app_cargo(team, region).get_apps()


def get_app_requirements(team: str, region: str, application: str) -> AppRequirements:
	"""What a server from one app asks the user for and needs to run."""
	return _app_cargo(team, region).get_app_requirements(application)


def _app_cargo(team: str, region: str) -> CargoClient:
	validate_catalog_access(team, "Server")
	instance = frappe.get_doc("Region", region)
	instance.ensure_accepts_new_servers()
	return CargoClient(instance)


def preview_images(
	offering: str, region: str, offset: int = 0, extra_tags: dict[str, str] | None = None
) -> dict:
	"""Check an operator's saved selector without creating a regional resource. The caller
	checks that the operator may edit what is previewed."""
	instance = frappe.get_doc("Region", region)
	client = AtlasClient.for_operator(instance)
	document = frappe.get_doc("Image Offering", offering)

	return client.list_system_images({**document.get_image_tags(), **(extra_tags or {})}, offset)


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
	instance.ensure_accepts_new_servers()

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
	instance.ensure_accepts_new_servers()

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
		frappe.throw(_("A snapshot of a Frappe server cannot be restored yet."))

	return row


def eligible_plans(team: str, region: str, offering: str, image_id: str, snapshot: str | None = None) -> dict:
	"""Combine billing eligibility with the selected image's disk requirement. A restore
	passes `snapshot` instead of an offering and image."""
	from math import ceil

	from central.billing.catalog.composition import composition_quantities
	from central.billing.catalog.server_plans import get_server_plans

	image = (
		snapshot_image(team, region, snapshot)
		if snapshot
		else selected_image(team, region, offering, image_id)
	)
	minimum = get_minimum_shape(image, get_image_app_requirements(region, image, snapshot))
	catalog = get_server_plans(team, cluster=region)
	groups = {}
	for name, plans in catalog["plans"].items():
		rows = [plan for plan in plans if is_shape_enough(composition_quantities(plan["includes"]), minimum)]
		if rows:
			groups[name] = rows

	profiles = []
	for profile in catalog["profiles"]:
		vcpu_steps = [
			vcpus
			for vcpus in profile["vcpu_steps"]
			if vcpus * MILLICORES_PER_VCPU >= minimum["cpu_millicores"]
			and vcpus * profile["ram_ratio"] * MIB_PER_GIB >= minimum["memory_mib"]
		]
		disk_steps = [size for size in profile["disk_steps"] if size * MIB_PER_GIB >= minimum["disk_mib"]]
		if vcpu_steps and disk_steps:
			profiles.append(
				{
					**profile,
					"vcpu_steps": vcpu_steps,
					"disk_steps": disk_steps,
					"disk_min": max(profile["disk_min"], ceil(minimum["disk_mib"] / MIB_PER_GIB)),
				}
			)

	return {**catalog, "plans": groups, "profiles": profiles, "image_id": image_id}


def get_image_app_requirements(
	region: str, image: dict, snapshot: str | None = None
) -> AppRequirements | None:
	"""What a new server from an app image needs, from the region's Cargo. A restored
	snapshot is already set up, and any other image has no app, so both need nothing."""
	if snapshot or image["tags"].get("purpose") != APP_PURPOSE:
		return None

	region_document = frappe.get_doc("Region", region)
	return CargoClient(region_document).get_app_requirements(image["tags"]["application"])


def get_minimum_shape(image: dict, requirements: AppRequirements | None) -> dict[str, int]:
	"""The smallest machine an image runs on: its root disk, and an app's minimum size."""
	minimum = (requirements or {}).get("minimum_size") or {}
	return {
		"cpu_millicores": minimum.get("cpu_millicores", 0),
		"memory_mib": minimum.get("memory_mib", 0),
		"disk_mib": max(image["rootfs_size_mib"], minimum.get("disk_mib", 0)),
	}


def is_shape_enough(quantities: dict[str, float], minimum: dict[str, int]) -> bool:
	"""Whether plan quantities, in vCPUs and GiB, reach a minimum shape in millicores and MiB."""
	from central.billing.catalog.composition import COMPUTE, DISK, MEMORY

	return (
		quantities.get(COMPUTE, 0) * MILLICORES_PER_VCPU >= minimum["cpu_millicores"]
		and quantities.get(MEMORY, 0) * MIB_PER_GIB >= minimum["memory_mib"]
		and quantities.get(DISK, 0) * MIB_PER_GIB >= minimum["disk_mib"]
	)


def validate_app_answer(name: str, item: AppInput, value: str) -> None:
	"""Throw a message that says what is wrong with one answer to an app input and what it takes."""
	label = item.get("label", name)
	if not APP_INPUT_NAME.fullmatch(name):
		frappe.throw(_("The app setting {0} is not a valid shell variable name.").format(name))
	if len(value) > item.get("max_length", 255):
		frappe.throw(_("{0} must be at most {1} characters.").format(label, item.get("max_length", 255)))
	if not value.isprintable():
		frappe.throw(
			_("{0} can contain only printable characters, with no line breaks or tabs.").format(label)
		)

	kind = item.get("type", "string")
	if kind == "email":
		validate_email_address(value, throw=True)
	elif kind == "domain" and not DOMAIN.fullmatch(value):
		frappe.throw(_("{0} must be a domain name in lowercase, such as app.example.com.").format(label))
	elif kind == "password":
		validate_app_password(label, value)
	if (pattern := item.get("pattern")) and not re.fullmatch(pattern, value):
		frappe.throw(
			_("{0} is not in the expected format. {1}").format(label, item.get("description", "")).strip()
		)


def validate_app_password(label: str, value: str) -> None:
	"""Refuse a password that zxcvbn scores below 3 of 4, with its advice on how to fix it."""
	result = test_password_strength(value)
	if result["score"] < 3:
		feedback = result["feedback"]
		advice = " ".join([feedback.get("warning") or "", *feedback.get("suggestions", [])]).strip()
		frappe.throw(
			_("{0} is too easy to guess. {1}").format(
				label, advice or _("Use a longer password made of a few uncommon words.")
			)
		)


def get_app_subdomain(region: str, answers: AppAnswers) -> str | None:
	"""The answer to the app's `site_name` input, which the regional proxy routes to the server
	once it has an address. It must be a free label in the region's zone."""
	subdomain = answers.get(SITE_NAME_INPUT, "").strip()
	if not subdomain:
		return None
	if not DNS_LABEL.fullmatch(subdomain):
		frappe.throw(
			_("Use lowercase letters, numbers and hyphens in the site name, starting and ending with one.")
		)

	domain = f"{subdomain}.{Region.get_zone(region)}"
	BlockedDomain.validate_assignment(domain)
	chosen_by_site = frappe.get_all(
		"Site",
		filters={"subdomain": subdomain, "server.region": region, "server.status": ["!=", "Terminated"]},
		limit=1,
	)
	subdomain_request_in_queue = frappe.db.exists(
		"Resource Action",
		{"action": "create", "region": region, "subdomain": subdomain, "status": ["in", PENDING_STATES]},
	)

	if frappe.db.exists("Site Domain", domain) or chosen_by_site or subdomain_request_in_queue:
		frappe.throw(_("{0} is already taken. Choose another site name.").format(domain))

	return subdomain
