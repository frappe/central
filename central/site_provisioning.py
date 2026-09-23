from __future__ import annotations

import re

import frappe
from frappe import _

from central.billing.catalog.server_plans import get_server_plans
from central.iam import resolve_team
from central.integrations.images import list_images
from central.server_provisioning import submit_request

SIGNUP_FLOW = "Signup"
# A trial is a site the image already carries, on the Frappe version a signup runs. The
# region tags what an image holds, and it matches a tag exactly, so an image that carries
# no tag is never taken for a yes.
SIGNUP_IMAGE_TAGS = {"has_site": "1", "frappe_version": "develop"}
# One DNS label: what a customer may name a site, and all the proxy will route.
SUBDOMAIN_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
RESERVED_SUBDOMAINS = frozenset({"admin", "atlas", "cargo", "proxy", "site", "www"})


def create_trial_site(team: str | None, subdomain: str, request_key: str) -> dict:
	"""Start the machine a new customer's trial site lives on, under the name they chose.

	The image already carries a built site, so the only work is to start the machine.
	That runs through the same creation path a bought server takes, which is what gives a
	trial the same record, retry and error handling. The name rides on the request,
	because the site it will rename does not exist until the region answers.

	The durable action queues the regional work after the request commits. The customer can
	return to the same action while Central finishes or recovers the operation."""

	team = resolve_team(frappe.session.user, team)
	subdomain = validated_subdomain(subdomain)
	configuration = trial_configuration(team)
	return submit_request(
		team=team,
		request_key=request_key,
		title=subdomain,
		resource_type="Site",
		subdomain=subdomain,
		**configuration,
	)


def validated_subdomain(subdomain: str) -> str:
	"""The customer's name, or a refusal saying why it cannot be theirs."""
	availability = subdomain_availability(subdomain)
	if not availability["available"]:
		frappe.throw(availability["reason"])

	return availability["subdomain"]


def subdomain_availability(subdomain: str) -> dict:
	"""Whether a name is free, and the full address it would become."""
	subdomain = (subdomain or "").strip().lower()
	zone = trial_zone()
	answer = {"subdomain": subdomain, "domain": zone, "fqdn": f"{subdomain}.{zone}"}

	if not SUBDOMAIN_PATTERN.fullmatch(subdomain):
		reason = _("Use lowercase letters, numbers and hyphens, starting and ending with one.")
	elif subdomain in RESERVED_SUBDOMAINS:
		reason = _("That name is reserved. Please choose another.")
	elif frappe.db.exists("Site", {"subdomain": subdomain}) or frappe.db.exists(
		"Site Domain", answer["fqdn"]
	):
		reason = _("That name is taken. Please choose another.")
	else:
		return {**answer, "available": True, "reason": None}

	return {**answer, "available": False, "reason": reason}


def trial_zone() -> str:
	"""The regional zone a trial site is named in."""
	regions = trial_regions()
	if not regions:
		frappe.throw(_("No region is offering trial sites right now. Please try again shortly."))

	return frappe.get_cached_value("Region", regions[0], "proxy_domain")


def trial_regions() -> list[str]:
	"""Regions that can serve a trial site at all.

	A region needs a proxy zone to serve one: a site's address is built from that zone, so
	a region without one can never give a site an address."""
	return frappe.get_all(
		"Region",
		filters={"status": "Active", "proxy_domain": ["is", "set"]},
		pluck="name",
		order_by="name asc",
	)


def trial_configuration(team: str) -> dict:
	"""The one region, image and plan a trial site starts on.

	The plan should hold the shape the Pilot image was baked at. A region restores a
	warm image from memory only when the vCPU, memory and disk all match, and a trial
	that misses the shape cold-boots instead."""
	offering = signup_offering()
	region, plan = trial_region_and_plan(team)
	images = list_images(team, region, offering, SIGNUP_FLOW, extra_tags=SIGNUP_IMAGE_TAGS)["items"]
	if not images:
		frappe.throw(_("No trial image is available right now. Please try again shortly."))

	newest = max(images, key=lambda image: image["created_at"])
	return {"region": region, "offering": offering, "image_id": newest["id"], "plan": plan}


def signup_offering() -> str:
	"""The image offering the signup flow builds on.

	An offering marked for signup alone wins over one shared with the server flow, so an
	operator can point signups at a dedicated image without hiding it from the catalog."""
	offerings = frappe.get_all(
		"Image Offering",
		filters={"enabled": 1, "available_in": ["in", [SIGNUP_FLOW, "Both"]]},
		fields=["name", "available_in"],
		order_by="title asc",
	)
	if not offerings:
		frappe.throw(_("No signup image offering is configured."))

	dedicated = [row for row in offerings if row.available_in == SIGNUP_FLOW]
	return (dedicated or offerings)[0].name


def trial_region_and_plan(team: str) -> tuple[str, str]:
	"""The first region that can serve this team a trial site, and its cheapest trial plan.

	The catalog decides which plans qualify, because it already narrows a trial team's
	menu to the ones an operator flagged Available on Trial."""
	for region in trial_regions():
		plans = [row for rows in get_server_plans(team, cluster=region)["plans"].values() for row in rows]
		if plans:
			return region, min(plans, key=lambda plan: plan["rate"])["plan"]

	frappe.throw(_("No region is offering trial sites right now. Please try again shortly."))
