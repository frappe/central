from __future__ import annotations

import frappe
from frappe import _

from central.sso import verify_cargo_token


def authenticate() -> dict:
	"""Verify the bearer token Cargo presents. Central signed it, so it verifies its own
	signature -- no shared secret."""
	header = frappe.get_request_header("Authorization") or ""
	if not header.startswith("Bearer "):
		frappe.throw(_("A Cargo bearer token is required."), frappe.AuthenticationError)

	return verify_cargo_token(header.removeprefix("Bearer ").strip())


# nosemgrep: guest-whitelisted-method -- authenticate() verifies Cargo's signed token below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def garage_tokens(region: str, vm_ids: list[str] | None = None) -> dict:
	"""The secrets every node of one region's Garage cluster boots with.

	Idempotent per region: asking twice returns the same values, so a retried provision
	cannot split a cluster into nodes that fail to recognise each other."""
	from central.services.storage import mint_cluster_tokens

	authenticate()
	if not isinstance(region, str) or not region:
		frappe.throw(_("A region is required to mint a cluster's tokens."), frappe.ValidationError)

	return mint_cluster_tokens(region)
