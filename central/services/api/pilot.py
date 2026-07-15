from __future__ import annotations

import frappe
from frappe import _

from central.api.pilot import pilot_credential_auth
from central.services.permissions import assert_site_owner


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def get_config(site: str, service: str) -> dict:
	"""A site pulls its managed-service connection config (gateway URL + secret) over
	the authenticated pilot channel. Only the site's owning team can read it."""
	return config_for_site(frappe.local.pilot_credential.team, site, service)


def config_for_site(team: str, site: str, service: str) -> dict:
	"""Resolve one site's delivered connection config. The transport/auth is the
	caller's job; this enforces team ownership and returns the stored secret."""
	assert_site_owner(site, team)

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
		"Site Service Credential", {"managed_service": managed_service, "site": site, "status": "Active"}, "name"
	)
