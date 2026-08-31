import frappe
from frappe import _

from central.integrations.cargo import verify_cargo_request


# nosemgrep: guest-whitelisted-method -- verify_cargo_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_request
def garage_tokens(region: str, vm_ids: list[str] | None = None) -> dict:
	"""The secrets every node of one region's Garage cluster boots with.

	Idempotent per region: asking twice returns the same values, so a retried provision
	cannot split a cluster into nodes that fail to recognise each other."""
	from central.services.storage import mint_cluster_tokens

	if not region:
		frappe.throw(_("A region is required to mint a cluster's tokens."), frappe.ValidationError)

	return mint_cluster_tokens(region)


# nosemgrep: guest-whitelisted-method -- verify_cargo_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_request
def register_cluster(region: str, base_url: str, s3_endpoint: str) -> dict:
	"""Tell Central a region's cluster is running and where to reach it."""
	from central.services.storage import activate_cluster

	if not (region and base_url and s3_endpoint):
		frappe.throw(_("A region, admin endpoint and S3 endpoint are required."), frappe.ValidationError)

	return activate_cluster(region, base_url, s3_endpoint)


# nosemgrep: guest-whitelisted-method -- verify_cargo_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_request
def report_failure(region: str, step: str, error: str) -> dict:
	"""Cargo could not bring a region's cluster up. The secrets stay so a retry reuses them."""
	from central.services.storage import record_cluster_failure

	if not region:
		frappe.throw(_("A region is required."), frappe.ValidationError)

	return record_cluster_failure(region, step or "unknown", error or "")
