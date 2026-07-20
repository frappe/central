from __future__ import annotations

import frappe
from frappe import _

from central.services.drivers.base import get_driver
from central.services.permissions import assert_capability, assert_site_owner


@frappe.whitelist()
def activate_service(team: str, service: str) -> dict:
	"""Activate a team's add-on (idempotent). Needs an active billing subscription in
	the service's plan category; LLM has no team-level provisioning, so it goes Active."""
	assert_capability(team, "service:manage")
	add_on = _get_active_service(service)

	subscription = _resolve_subscription(team, add_on)
	if not subscription:
		frappe.throw(_("Team {0} has no active subscription for {1}.").format(team, add_on.title))

	existing = frappe.db.get_value(
		"Managed Service", {"team": team, "add_on_service": add_on.name}, ["name", "status"], as_dict=True
	)
	if existing:
		return {"managed_service": existing.name, "status": existing.status}

	doc = frappe.new_doc("Managed Service")
	doc.update({"team": team, "add_on_service": add_on.name, "subscription": subscription, "status": "Active"})
	doc.insert()

	return {"managed_service": doc.name, "status": doc.status}


@frappe.whitelist()
def enable_site(managed_service: str, site: str) -> dict:
	"""Provision the per-site credential and store it. The secret is never returned
	here — the site pulls it over the authenticated pilot channel via get_config."""
	service = frappe.db.get_value(
		"Managed Service", managed_service, ["team", "status", "add_on_service", "subscription"], as_dict=True
	)
	if not service:
		frappe.throw(_("Unknown managed service."))
	assert_capability(service.team, "service:manage")

	if service.status != "Active":
		frappe.throw(_("Managed service is not active."))
	assert_site_owner(site, service.team)

	# Reuse the (managed_service, site) row across enable/disable — a fresh insert
	# would collide with a revoked credential on the unique index.
	existing = frappe.db.get_value(
		"Site Service Credential", {"managed_service": managed_service, "site": site}, ["name", "status"], as_dict=True
	)
	if existing and existing.status == "Active":
		return {"credential": existing.name, "site": site, "status": "Active"}

	add_on = _get_active_service(service.add_on_service)
	backend = _get_backend(add_on.name)
	options = _provision_options(add_on.handler_key, service.subscription)
	result = get_driver(add_on.handler_key).provision_site(backend, site, options)

	credential = frappe.get_doc("Site Service Credential", existing.name) if existing else frappe.new_doc(
		"Site Service Credential"
	)
	credential.update(
		{
			"managed_service": managed_service,
			"site": site,
			"status": "Active",
			"gateway_url": result["gateway_url"],
			"provider_ref": result.get("provider_ref"),
			"api_key": result["api_key"],
		}
	)
	credential.save()

	return {"credential": credential.name, "site": site, "gateway_url": result["gateway_url"], "status": "Active"}


@frappe.whitelist()
def disable_site(managed_service: str, site: str) -> dict:
	"""Revoke a site's credential at the provider and mark it revoked."""
	service = frappe.db.get_value("Managed Service", managed_service, ["team", "add_on_service"], as_dict=True)
	if not service:
		frappe.throw(_("Unknown managed service."))
	assert_capability(service.team, "service:manage")

	credential_name = frappe.db.get_value(
		"Site Service Credential", {"managed_service": managed_service, "site": site, "status": "Active"}, "name"
	)
	if not credential_name:
		return {"site": site, "status": "not_enabled"}

	credential = frappe.get_doc("Site Service Credential", credential_name)
	add_on = _get_active_service(service.add_on_service)
	get_driver(add_on.handler_key).revoke_site(_get_backend(add_on.name), credential.get_password("api_key"))

	credential.db_set("status", "Revoked")

	return {"site": site, "status": "Revoked"}


@frappe.whitelist(methods=["GET"])
def list_offers(team: str) -> list[dict]:
	"""Catalogue of active add-on services with the team's status for each. service:view."""
	assert_capability(team, "service:view")

	offers = frappe.get_all(
		"Add-on Service", filters={"is_active": 1}, fields=["name", "title", "plan_category"], order_by="title"
	)
	activated = {
		row.add_on_service: row.name
		for row in frappe.get_all("Managed Service", filters={"team": team}, fields=["name", "add_on_service"])
	}
	for offer in offers:
		offer["managed_service"] = activated.get(offer.name)

	return offers


@frappe.whitelist(methods=["GET"])
def get_instance(managed_service: str) -> dict:
	"""A managed service's status, enabled sites, and included models. service:view."""
	instance = frappe.db.get_value(
		"Managed Service", managed_service, ["name", "team", "add_on_service", "subscription", "status"], as_dict=True
	)
	if not instance:
		frappe.throw(_("Unknown managed service."))
	assert_capability(instance.team, "service:view")

	sites = frappe.get_all(
		"Site Service Credential",
		filters={"managed_service": managed_service, "status": "Active"},
		fields=["site", "gateway_url"],
		order_by="site",
	)
	plan = frappe.db.get_value("Subscription", instance.subscription, "plan")

	return {
		"managed_service": instance.name,
		"service": instance.add_on_service,
		"status": instance.status,
		"plan": plan,
		"enabled_sites": [row.site for row in sites],
		"models": _included_models(instance.add_on_service, plan),
	}


@frappe.whitelist(methods=["GET"])
def list_sites(team: str) -> list[dict]:
	"""A team's sites from the Site mirror. Backs the Sites tab and the site-first
	console surface for single-site teams. service:view."""
	assert_capability(team, "service:view")

	return frappe.get_all("Site", filters={"team": team}, fields=["name", "status", "url"], order_by="name")


def _included_models(service: str, plan: str | None) -> list[dict]:
	if frappe.db.get_value("Add-on Service", service, "handler_key", cache=True) != "grove":
		return []

	from central.services import llm

	return llm.included_models(plan)


def _get_active_service(service: str):
	add_on = frappe.db.get_value(
		"Add-on Service", service, ["name", "title", "handler_key", "plan_category", "is_active"], as_dict=True, cache=True
	)
	if not add_on or not add_on.is_active:
		frappe.throw(_("Unknown or inactive service '{0}'.").format(service))

	return add_on


def _get_backend(service: str):
	name = frappe.db.get_value("Service Backend", {"service": service, "is_active": 1}, "name")
	if not name:
		frappe.throw(_("No active backend configured for {0}.").format(service))

	return frappe.get_doc("Service Backend", name)


def _provision_options(handler_key: str, subscription: str) -> dict:
	# Only the LLM handler derives model/token policy from the plan today.
	if handler_key != "grove":
		return {}

	from central.services import llm

	return llm.resolve_provision_options(frappe.db.get_value("Subscription", subscription, "plan"))


def _resolve_subscription(team: str, add_on) -> str | None:
	# The team's active subscription whose plan sits in the service's billing family.
	plans = frappe.get_all("Plan", filters={"category": add_on.plan_category}, pluck="name")
	if not plans:
		return None

	return frappe.db.get_value("Subscription", {"team": team, "enabled": 1, "plan": ["in", plans]}, "name")
