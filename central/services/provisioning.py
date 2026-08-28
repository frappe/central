from __future__ import annotations

import typing

import frappe
from frappe import _

from central.services.drivers.base import get_driver

if typing.TYPE_CHECKING:
	from central.services.doctype.add_on_service.add_on_service import AddonService
	from central.services.doctype.service_backend.service_backend import ServiceBackend

# The minting core: Central owns entitlement + key issuance + storage. Who triggers a
# site enable (the bench/Pilot, an operator) is the API layer's concern — this module
# only mints, stores, and revokes. Ownership is not re-checked here: the credential is
# stored under a team's Managed Service, so it is team-scoped by construction; the
# caller is responsible for authenticating the team.


def active_managed_service(team: str, service: str) -> str:
	"""The team's active entitlement for a service. Activation is a Central-console
	billing decision, so a site can only be enabled once the team has activated."""
	managed_service = frappe.db.get_value(
		"Managed Service", {"team": team, "add_on_service": service, "status": "Active"}, "name"
	)
	if not managed_service:
		frappe.throw(_("{0} is not enabled for this team.").format(service))

	return managed_service


def enable_site(managed_service: str, site: str) -> dict:
	"""Mint (or reuse) a site's provider credential and store it. Idempotent per
	(managed_service, site) — the row is reused across enable/disable."""
	service = get_managed_service(managed_service)
	add_on = get_active_service(service.add_on_service)

	existing = frappe.db.get_value(
		"Service Credential",
		{"subject_type": "Site", "managed_service": managed_service, "site": site},
		["name", "status"],
		as_dict=True,
	)
	if existing and existing.status == "Active":
		stored = frappe.get_doc("Service Credential", existing.name)
		return _config(existing.name, site, stored.gateway_url, stored.get_password("api_key"))

	backend = get_backend(add_on.name)
	options = provision_options(add_on.handler_key, service.subscription)
	result = get_driver(add_on.handler_key).provision_site(backend, site, options)

	credential = (
		frappe.get_doc("Service Credential", existing.name)
		if existing
		else frappe.new_doc("Service Credential")
	)
	credential.update(
		{
			"subject_type": "Site",
			"managed_service": managed_service,
			"site": site,
			"status": "Active",
			"gateway_url": result["gateway_url"],
			"provider_ref": result.get("provider_ref"),
			"api_key": result["api_key"],
		}
	)
	try:
		credential.save()
	except Exception:
		# The key was minted but nothing records it: its secret never left Central, so
		# revoke rather than leave it live at the provider, untracked.
		_revoke_quietly(add_on.handler_key, backend, result["api_key"])
		raise

	return _config(credential.name, site, result["gateway_url"], result["api_key"])


def _revoke_quietly(handler_key: str, backend, api_key: str) -> None:
	"""Best-effort cleanup: a failed revoke must not replace the error being re-raised."""
	try:
		get_driver(handler_key).revoke_site(backend, api_key)
	except Exception:
		frappe.log_error(
			title="Provider key left behind after a failed provision",
			message=f"A key minted at {backend.name} is still live.\n\n{frappe.get_traceback()}",
		)


def disable_site(managed_service: str, site: str) -> dict:
	"""Revoke a site's credential at the provider and mark it revoked."""
	credential_name = frappe.db.get_value(
		"Service Credential",
		{"subject_type": "Site", "managed_service": managed_service, "site": site, "status": "Active"},
		"name",
	)
	if not credential_name:
		return {"site": site, "status": "not_enabled"}

	credential = frappe.get_doc("Service Credential", credential_name)
	add_on = get_active_service(get_managed_service(managed_service).add_on_service)
	get_driver(add_on.handler_key).revoke_site(get_backend(add_on.name), credential.get_password("api_key"))
	credential.db_set("status", "Revoked")

	return {"site": site, "status": "Revoked"}


def _config(credential: str, site: str, gateway_url: str, api_key: str) -> dict:
	return {
		"credential": credential,
		"site": site,
		"gateway_url": gateway_url,
		"api_key": api_key,
		"status": "Active",
	}


def get_managed_service(managed_service: str):
	service = frappe.db.get_value(
		"Managed Service",
		managed_service,
		["name", "team", "status", "add_on_service", "subscription"],
		as_dict=True,
	)
	if not service:
		frappe.throw(_("Unknown managed service."))

	return service


def get_active_service(service: str) -> AddonService:
	add_on = frappe.db.get_value(
		"Add-on Service",
		service,
		["name", "title", "handler_key", "plan_category", "is_active"],
		as_dict=True,
		cache=True,
	)
	if not add_on or not add_on.is_active:
		frappe.throw(_("Unknown or inactive service '{0}'.").format(service))

	return add_on


def get_backend(service: str) -> ServiceBackend:
	name = frappe.db.get_value("Service Backend", {"service": service, "is_active": 1}, "name")
	if not name:
		frappe.throw(_("No active backend configured for {0}.").format(service))

	return frappe.get_doc("Service Backend", name)


def provision_options(handler_key: str, subscription: str) -> dict:
	# Only the LLM handler derives model/token policy from the plan today.
	if handler_key != "grove":
		return {}

	from central.services import llm

	return llm.resolve_provision_options(frappe.db.get_value("Subscription", subscription, "plan"))
