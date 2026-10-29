from __future__ import annotations

import time

import frappe
from frappe import _

from central.billing.catalog.server_plans import get_server_plans
from central.billing.catalog.trials import trial_plan_names
from central.iam import get_user_team_names, resolve_team
from central.identity.doctype.team.team import Team
from central.infrastructure.doctype.blocked_domain.blocked_domain import BlockedDomain, normalize_domain
from central.integrations.images import list_images
from central.resource_actions import submit_request
from central.server_models import DNS_LABEL, SiteCreation
from central.signups.doctype.product.product import Product, get_signup_product

SIGNUP_FLOW = "Signup"
# A trial is a site the image already carries, on the Frappe version a signup runs. A
# product names its own version. The region tags what an image holds, and it matches a tag
# exactly, so an image that carries no tag is never taken for a yes.
SIGNUP_IMAGE_TAGS = {"has_site": "1", "frappe_version": "version-16-hotfix"}
# Cargo tags an image with the signup app installed on its site. A product trial asks for
# its app. A plain trial starts on the bare site, and the region cannot filter on a missing
# tag, so Central drops tagged images itself.
SIGNUP_APP_TAG = "app"


def create_trial_site(team: str | None, subdomain: str, request_key: str, product: str) -> dict:
	"""Start the machine for a product's new trial site, under the name the customer chose. It takes
	the same creation path as a bought server, so a trial gets the same record, retry and errors."""

	team = resolve_team(frappe.session.user, team)
	signup_product = get_signup_product(product)
	subdomain = validated_subdomain(subdomain)
	configuration = trial_configuration(team, signup_product)
	site = SiteCreation(product=product)

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
	"""Whether a name is free. It is checked in every trial zone, because the region a trial
	lands in is chosen only when it is created."""
	subdomain = normalize_domain(subdomain)
	answer = {"subdomain": subdomain}

	if not DNS_LABEL.fullmatch(subdomain):
		reason = _("Use lowercase letters, numbers and hyphens, starting and ending with one.")
	elif any(
		BlockedDomain.is_blocked(f"{subdomain}.{frappe.get_cached_value('Region', region, 'proxy_domain')}")
		for region in trial_regions()
	):
		reason = _("That name is reserved. Please choose another.")
	elif is_subdomain_taken(subdomain):
		reason = _("That name is taken. Please choose another.")
	else:
		return {**answer, "available": True, "reason": None}

	return {**answer, "available": False, "reason": reason}


def is_subdomain_taken(subdomain: str) -> bool:
	"""Taken as the chosen name of a site on a live server, which exists before the rename
	routes it, or as a route in any trial zone. A route holds its name until its removal
	succeeds, even for a terminated server, because registration refuses a name in use."""
	domains = [
		f"{subdomain}.{frappe.get_cached_value('Region', region, 'proxy_domain')}"
		for region in trial_regions()
	]
	site_filters = {"subdomain": subdomain, "server.status": ["!=", "Terminated"]}
	if frappe.get_all("Site", filters=site_filters, limit=1):
		return True

	return bool(domains) and bool(frappe.db.exists("Site Domain", {"name": ["in", domains]}))


def trial_zone(team: str, product: Product | None = None) -> str:
	"""The zone of the region a trial site of this team and product starts in."""
	region = trial_configuration(team, product)["region"]
	return frappe.get_cached_value("Region", region, "proxy_domain")


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


def trial_configuration(team: str, product: Product | None = None) -> dict:
	"""The region, image and plan a trial site starts on: the first region that offers this team
	a trial plan and has a trial image. The plan must match the shape the image was baked at,
	or the region cold-boots instead of restoring a warm image."""
	offering = signup_offering()
	has_plan = False
	for region in trial_regions():
		plan = get_cheapest_trial_plan(team, region)
		if not plan:
			continue

		has_plan = True
		if images := trial_images(team, region, offering, product):
			minimum_age = frappe.get_cached_doc("Central Settings").signup_image_minimum_age_minutes
			cutoff = time.time() - minimum_age * 60
			preferred = (
				[image for image in images if image["created_at"] <= cutoff] if minimum_age else images
			)
			newest = max(preferred or images, key=lambda image: image["created_at"])
			return {"region": region, "offering": offering, "image_id": newest["id"], "plan": plan}

	if not has_plan:
		frappe.throw(_("No region is offering trial sites right now. Please try again shortly."))
	frappe.throw(_("No trial image is available right now. Please try again shortly."))


def trial_images(team: str, region: str, offering: str, product: Product | None) -> list[dict]:
	"""The region's trial images with the product's app installed, or with no app at all."""
	tags = product_image_tags(product) if product else SIGNUP_IMAGE_TAGS
	images = []
	offset = 0
	while True:
		page = list_images(team, region, offering, SIGNUP_FLOW, offset=offset, extra_tags=tags)
		images.extend(page["items"])
		if (offset := page.get("next_offset")) is None:
			break

	return images if product else [image for image in images if SIGNUP_APP_TAG not in image["tags"]]


def product_image_tags(product: Product) -> dict[str, str]:
	"""The tags of a trial image that has the product's app installed on its Frappe version."""
	return {
		**SIGNUP_IMAGE_TAGS,
		"frappe_version": product.frappe_version,
		SIGNUP_APP_TAG: product.signup_app,
	}


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


def get_cheapest_trial_plan(team: str, region: str) -> str | None:
	"""The cheapest marked trial plan in the Team's regional catalog, or None."""
	trial_plans = trial_plan_names()
	if not trial_plans:
		return None

	plans = [
		row
		for rows in get_server_plans(team, cluster=region, include_trial_plans=True)["plans"].values()
		for row in rows
		if row["plan"] in trial_plans
	]
	return min(plans, key=lambda plan: plan["rate"])["plan"] if plans else None
