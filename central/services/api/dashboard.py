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
		frappe.throw(
			_("{0} is not available in this team's plan. Ask your account administrator to add it, then try again.").format(
				add_on.title
			)
		)

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


@frappe.whitelist(methods=["POST"])
def get_credential(managed_service: str, site: str) -> dict:
	"""Reveal one site's live connection config for bring-your-own use (curl, external
	apps). Returns the secret, so it needs service:manage — this is the console's
	explicit "reveal key" action, not a passive read."""
	service = frappe.db.get_value("Managed Service", managed_service, ["team"], as_dict=True)
	if not service:
		frappe.throw(_("Unknown managed service."))
	assert_capability(service.team, "service:manage")

	credential_name = frappe.db.get_value(
		"Site Service Credential", {"managed_service": managed_service, "site": site, "status": "Active"}, "name"
	)
	if not credential_name:
		frappe.throw(_("Service is not enabled for site {0}.").format(site))

	stored = frappe.get_doc("Site Service Credential", credential_name)
	return {
		"site": site,
		"gateway_url": stored.gateway_url,
		"api_key": stored.get_password("api_key"),
		"provider_ref": stored.provider_ref,
		"status": stored.status,
	}


@frappe.whitelist(methods=["POST"])
def generate_api_key(managed_service: str, label: str) -> dict:
	"""Mint a team-level inference key for use in the customer's own apps. Same plan
	gating and token meter as a site key — just not tied to a site. service:manage.
	The secret is returned once here and re-readable later via reveal_api_key."""
	service = _managed_service(managed_service, "service:manage")
	if service.status != "Active":
		frappe.throw(_("Managed service is not active."))

	label = (label or "").strip()
	if not label:
		frappe.throw(_("A label is required."))

	add_on = _get_active_service(service.add_on_service)
	backend = _get_backend(add_on.name)
	options = _provision_options(add_on.handler_key, service.subscription)

	# Provision first, persist second: a provider failure leaves no orphan row. A random
	# email is this key's meterable Grove identity, so usage attributes to it alone.
	email = f"key-{frappe.generate_hash(length=12)}@svc.frappe.cloud"
	result = get_driver(add_on.handler_key).provision_key(backend, label, email, options)

	doc = frappe.new_doc("Service API Key")
	doc.update(
		{
			"managed_service": managed_service,
			"label": label,
			"status": "Active",
			"gateway_url": result["gateway_url"],
			"provider_ref": result.get("provider_ref", email),
			"api_key": result["api_key"],
		}
	)
	doc.insert()

	return {
		"name": doc.name,
		"label": label,
		"gateway_url": result["gateway_url"],
		"api_key": result["api_key"],
		"status": "Active",
	}


@frappe.whitelist(methods=["GET"])
def list_api_keys(managed_service: str) -> list[dict]:
	"""A managed service's issued API keys (no secrets). service:view."""
	_managed_service(managed_service, "service:view")

	return frappe.get_all(
		"Service API Key",
		filters={"managed_service": managed_service},
		fields=["name", "label", "status", "gateway_url", "last_usage_total", "creation"],
		order_by="creation desc",
	)


@frappe.whitelist(methods=["POST"])
def reveal_api_key(name: str) -> dict:
	"""Reveal one issued key's secret + endpoint for copy/curl. service:manage."""
	doc = frappe.get_doc("Service API Key", name)
	_managed_service(doc.managed_service, "service:manage")
	if doc.status != "Active":
		frappe.throw(_("This key has been revoked."))

	return {
		"name": doc.name,
		"label": doc.label,
		"gateway_url": doc.gateway_url,
		"api_key": doc.get_password("api_key"),
	}


@frappe.whitelist(methods=["POST"])
def revoke_api_key(name: str) -> dict:
	"""Revoke an issued key at the provider and mark it revoked. service:manage."""
	doc = frappe.get_doc("Service API Key", name)
	service = _managed_service(doc.managed_service, "service:manage")
	if doc.status == "Revoked":
		return {"name": name, "status": "Revoked"}

	add_on = _get_active_service(service.add_on_service)
	get_driver(add_on.handler_key).revoke_site(_get_backend(add_on.name), doc.get_password("api_key"))
	doc.db_set("status", "Revoked")

	return {"name": name, "status": "Revoked"}


def _managed_service(managed_service: str, capability: str):
	service = frappe.db.get_value(
		"Managed Service", managed_service, ["name", "team", "status", "add_on_service", "subscription"], as_dict=True
	)
	if not service:
		frappe.throw(_("Unknown managed service."))
	assert_capability(service.team, capability)

	return service


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
		"plan_title": frappe.db.get_value("Plan", plan, "title") if plan else None,
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
