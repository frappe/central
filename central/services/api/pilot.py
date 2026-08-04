from __future__ import annotations

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.services import provisioning

# The bench↔Central service surface. The bench (Pilot) is authoritative for "these
# are my sites" and drives enable/disable per site; Central owns entitlement + key
# issuance + billing. Ownership comes from the authenticated pilot credential's team,
# not Central's site mirror — so these serve sites Central never mirrored.


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def enable(site: str, service: str) -> dict:
	"""Enable a managed service on one of the bench's sites. Requires the team to have
	activated the service (a Central-console billing step). Returns the connection
	config so the bench can inject it immediately."""
	team = frappe.local.pilot_credential.team
	managed_service = provisioning.active_managed_service(team, service)
	result = provisioning.enable_site(managed_service, site)

	return {
		"service": service,
		"gateway_url": result["gateway_url"],
		"api_key": result["api_key"],
		"status": result["status"],
	}


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def disable(site: str, service: str) -> dict:
	"""Disable a managed service on one of the bench's sites — revokes the key."""
	team = frappe.local.pilot_credential.team
	managed_service = frappe.db.get_value(
		"Managed Service", {"team": team, "add_on_service": service}, "name"
	)
	if not managed_service:
		return {"site": site, "status": "not_enabled"}

	return provisioning.disable_site(managed_service, site)


# nosemgrep: guest-whitelisted-method -- pilot_credential_auth verifies the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def get_config(site: str, service: str) -> dict:
	"""A site pulls its delivered connection config (gateway URL + secret) over the
	authenticated pilot channel."""
	return config_for_site(frappe.local.pilot_credential.team, site, service)


def config_for_site(team: str, site: str, service: str) -> dict:
	"""Resolve one site's delivered config. Team-scoped by the credential lookup (the
	credential lives under the team's Managed Service), so there is no separate site
	mirror check — which also lets it serve bench-enabled sites Central never mirrored."""
	credential_name = _resolve_credential(team, service, site)
	if not credential_name:
		frappe.throw(_("Service {0} is not enabled for site {1}.").format(service, site))

	stored = frappe.get_doc("Site Service Credential", credential_name)
	return {
		"service": service,
		"gateway_url": stored.gateway_url,
		"api_key": stored.get_password("api_key"),
	}


def _resolve_credential(team: str, service: str, site: str) -> str | None:
	managed_service = frappe.db.get_value(
		"Managed Service", {"team": team, "add_on_service": service, "status": "Active"}, "name"
	)
	if not managed_service:
		return None

	return frappe.db.get_value(
		"Site Service Credential",
		{"managed_service": managed_service, "site": site, "status": "Active"},
		"name",
	)
