from __future__ import annotations

import frappe
from frappe import _

from central.billing.catalog.server_plans import get_server_plans
from central.iam import get_user_team_names, resolve_team
from central.identity.doctype.team.team import Team
from central.integrations.images import list_images
from central.resource_actions import submit_request
from central.server_models import DNS_LABEL, SiteCreation
from central.signups.doctype.product.product import get_signup_product

SIGNUP_FLOW = "Signup"
# A trial is a site the image already carries, on the Frappe version a signup runs. The
# region tags what an image holds, and it matches a tag exactly, so an image that carries
# no tag is never taken for a yes.
SIGNUP_IMAGE_TAGS = {"has_site": "1", "frappe_version": "develop"}
# Cargo tags an image with the signup app installed on its site. A product trial asks for
# its app. A plain trial starts on the bare site, and the region cannot filter on a missing
# tag, so Central drops tagged images itself.
SIGNUP_APP_TAG = "app"
# One DNS label: what a customer may name a site, and all the proxy will route.
RESERVED_SUBDOMAINS = frozenset({"admin", "atlas", "cargo", "proxy", "site", "www"})


def create_trial_site(
	team: str | None,
	subdomain: str,
	request_key: str,
	product: str | None = None,
) -> dict:
	"""Start the machine for a new trial site, under the name the customer chose. It takes the
	same creation path as a bought server, so a trial gets the same record, retry and errors."""

	team = resolve_team(frappe.session.user, team)
	signup_app = get_signup_product(product).signup_app if product else None
	subdomain = validated_subdomain(subdomain)
	configuration = trial_configuration(team, signup_app)
	site = SiteCreation(product=product or None)

	return submit_request(
		team=team,
		request_key=request_key,
		title=subdomain,
		resource_type="Site",
		subdomain=subdomain,
		site=site,
		**configuration,
	)


def create_trial_team(user: str, attribution: dict | None = None) -> str | None:
	"""Create the first team of a user who starts the trial funnel with none.

	The funnel cannot ask for a team name, so the team is named after the user. A
	user who already has a team keeps it, and nothing is created."""
	if get_user_team_names(user):
		return None

	full_name = frappe.db.get_value("User", user, "full_name") or user
	team_name = _("{0}'s Team").format(full_name)

	return Team.create_for_current_user(team_name, first_touch(**(attribution or {}))).name


def first_touch(
	utm_source: str | None = None,
	utm_medium: str | None = None,
	utm_campaign: str | None = None,
	referrer: str | None = None,
	product: str | None = None,
) -> dict:
	"""How the signup first found us, trimmed to fit the team. It only labels the team,
	so a bad value is dropped instead of refusing the signup."""
	return {
		"utm_source": _clip(utm_source, 140),
		"utm_medium": _clip(utm_medium, 140),
		"utm_campaign": _clip(utm_campaign, 140),
		"referrer": _clip(referrer, 1000),
		"landing_product": product if product and frappe.db.exists("Product", product) else None,
	}


def _clip(value: str | None, length: int) -> str | None:
	return (value.strip()[:length] or None) if isinstance(value, str) else None


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

	if not DNS_LABEL.fullmatch(subdomain):
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


def trial_configuration(team: str, signup_app: str | None = None) -> dict:
	"""The region, image and plan a trial site starts on. The plan must match the shape the
	image was baked at, or the region cold-boots instead of restoring a warm image."""
	offering = signup_offering()
	region, plan = trial_region_and_plan(team)
	images = trial_images(team, region, offering, signup_app)
	if not images:
		frappe.throw(_("No trial image is available right now. Please try again shortly."))

	newest = max(images, key=lambda image: image["created_at"])

	return {"region": region, "offering": offering, "image_id": newest["id"], "plan": plan}


def trial_images(team: str, region: str, offering: str, signup_app: str | None) -> list[dict]:
	"""The region's trial images with the signup app installed, or with no app at all."""
	if signup_app:
		tags = product_image_tags(signup_app)
		return list_images(team, region, offering, SIGNUP_FLOW, extra_tags=tags)["items"]

	images = list_images(team, region, offering, SIGNUP_FLOW, extra_tags=SIGNUP_IMAGE_TAGS)["items"]

	return [image for image in images if SIGNUP_APP_TAG not in image["tags"]]


def product_image_tags(signup_app: str) -> dict[str, str]:
	"""The tags of a trial image that has the product's app installed."""
	return {**SIGNUP_IMAGE_TAGS, SIGNUP_APP_TAG: signup_app}


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
