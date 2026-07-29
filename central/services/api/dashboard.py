from __future__ import annotations

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

from central.services import provisioning
from central.services.drivers.base import get_driver
from central.services.permissions import require_service_capability

# Every endpoint is a capability-gated whitelisted method rather than the native
# DocType list/get: team access to services is governed by capability IAM
# (central.iam), not Frappe roles, so team users hold no DocType permission — and the
# read shapes are curated for the console. @require_service_capability resolves the
# team from the call (team | managed_service | key name) and checks the capability.
#
# Per-site enable/disable is NOT here: the bench (Pilot) is authoritative for its
# sites and drives that via central.services.api.pilot. Central owns team activation
# (below), team-level API keys, and the read surfaces.


@frappe.whitelist()
@require_service_capability("service:manage")
def activate_service(team: str, service: str) -> dict:
	"""Activate a team's add-on (idempotent). Needs an active billing subscription in
	the service's plan category; LLM has no team-level provisioning, so it goes Active."""
	add_on = provisioning.get_active_service(service)

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


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def generate_api_key(managed_service: str, label: str) -> dict:
	"""Mint a team-level inference key for use in the customer's own apps. Same plan
	gating and token meter as a site key — just not tied to a site. The secret is
	returned once here and re-readable later via reveal_api_key."""
	service = provisioning.get_managed_service(managed_service)
	if service.status != "Active":
		frappe.throw(_("Managed service is not active."))

	label = (label or "").strip()
	if not label:
		frappe.throw(_("A label is required."))

	add_on = provisioning.get_active_service(service.add_on_service)
	backend = provisioning.get_backend(add_on.name)
	options = provisioning.provision_options(add_on.handler_key, service.subscription)

	# Provision first, persist second: a provider failure leaves no orphan row. A random
	# email is this key's meterable Grove identity, so usage attributes to it alone. If
	# insert dies after minting, the key's secret is never disclosed, so it's inert.
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
@require_service_capability("service:view")
def list_api_keys(managed_service: str) -> list[dict]:
	"""A managed service's issued API keys, masked (no raw secrets). service:view."""
	rows = frappe.get_all(
		"Service API Key",
		filters={"managed_service": managed_service},
		fields=["name", "label", "status", "gateway_url", "last_usage_total", "creation"],
		order_by="creation desc",
	)
	for row in rows:
		row["masked_key"] = _mask_key(get_decrypted_password("Service API Key", row.name, "api_key"))

	return rows


def _mask_key(key: str) -> str:
	return f"{key[:6]}••••{key[-4:]}" if key and len(key) > 10 else "••••"


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def reveal_api_key(name: str) -> dict:
	"""Reveal one issued key's secret + endpoint for copy/curl. service:manage."""
	doc = frappe.get_doc("Service API Key", name)
	if doc.status != "Active":
		frappe.throw(_("This key has been revoked."))

	return {
		"name": doc.name,
		"label": doc.label,
		"gateway_url": doc.gateway_url,
		"api_key": doc.get_password("api_key"),
	}


@frappe.whitelist(methods=["POST"])
@require_service_capability("service:manage")
def revoke_api_key(name: str) -> dict:
	"""Revoke an issued key at the provider and mark it revoked. service:manage."""
	doc = frappe.get_doc("Service API Key", name)
	if doc.status == "Revoked":
		return {"name": name, "status": "Revoked"}

	add_on = provisioning.get_active_service(provisioning.get_managed_service(doc.managed_service).add_on_service)
	get_driver(add_on.handler_key).revoke_site(provisioning.get_backend(add_on.name), doc.get_password("api_key"))
	doc.db_set("status", "Revoked")

	return {"name": name, "status": "Revoked"}


@frappe.whitelist(methods=["GET"])
@require_service_capability("service:view")
def list_offers(team: str) -> list[dict]:
	"""Catalogue of active add-on services with the team's status for each. service:view."""
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
@require_service_capability("service:view")
def get_instance(managed_service: str) -> dict:
	"""A managed service's status, enabled sites, and included models. service:view.
	`enabled_sites` are the sites Central has minted keys for — its own record, not a
	VM scan (the bench owns the authoritative site list)."""
	instance = provisioning.get_managed_service(managed_service)
	sites = frappe.get_all(
		"Site Service Credential",
		filters={"managed_service": managed_service, "status": "Active"},
		fields=["site", "gateway_url"],
		order_by="site",
	)
	clusters = frappe.get_all(
		"Site", filters={"name": ["in", [row.site for row in sites]]}, fields=["name", "cluster"]
	)
	cluster_by_site = {row.name: row.cluster for row in clusters}
	plan = frappe.db.get_value("Subscription", instance.subscription, "plan")

	return {
		"managed_service": instance.name,
		"service": instance.add_on_service,
		"status": instance.status,
		"plan": plan,
		"plan_title": frappe.db.get_value("Plan", plan, "title") if plan else None,
		"enabled_sites": [{"site": row.site, "cluster": cluster_by_site.get(row.site)} for row in sites],
		"models": _included_models(instance.add_on_service, plan),
	}


def _included_models(service: str, plan: str | None) -> list[dict]:
	if frappe.db.get_value("Add-on Service", service, "handler_key", cache=True) != "grove":
		return []

	from central.services import llm

	return llm.included_models(plan)


def _resolve_subscription(team: str, add_on) -> str | None:
	# The team's active subscription whose plan sits in the service's billing family.
	plans = frappe.get_all("Plan", filters={"category": add_on.plan_category}, pluck="name")
	if not plans:
		return None

	return frappe.db.get_value("Subscription", {"team": team, "enabled": 1, "plan": ["in", plans]}, "name")
