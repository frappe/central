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


# nosemgrep: guest-whitelisted-method -- authenticate() verifies Cargo's signed token below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_cluster(region: str, base_url: str, s3_endpoint: str) -> dict:
	"""Tell Central a region's cluster is running and where to reach it."""
	from central.services.storage import activate_cluster

	authenticate()
	if not all(isinstance(value, str) and value for value in (region, base_url, s3_endpoint)):
		frappe.throw(_("A region, admin endpoint and S3 endpoint are required."), frappe.ValidationError)

	return activate_cluster(region, base_url, s3_endpoint)


# nosemgrep: guest-whitelisted-method -- authenticate() verifies Cargo's signed token below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_failure(region: str, step: str, error: str) -> dict:
	"""Cargo could not bring a region's cluster up. The secrets stay so a retry reuses them."""
	from central.services.storage import record_cluster_failure

	authenticate()
	if not region:
		frappe.throw(_("A region is required."), frappe.ValidationError)

	return record_cluster_failure(region, step or "unknown", error or "")
