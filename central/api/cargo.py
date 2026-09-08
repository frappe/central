import typing

import frappe
from frappe import _

from central.integrations.cargo import verify_cargo_bootstrapping_request, verify_cargo_request

if typing.TYPE_CHECKING:
	from central.central.doctype.internal_service.internal_service import InternalService


# nosemgrep: guest-whitelisted-method -- verify_cargo_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_request
def garage_tokens(region: str, vm_ids: list[str] | None = None) -> dict:
	"""The secrets every node of one region's Garage cluster boots with.

	Idempotent per region: asking twice returns the same values, so a retried provision
	cannot split a cluster into nodes that fail to recognise each other. `region` must be
	the one the caller's token was minted for."""
	from central.services.storage import mint_cluster_tokens

	return mint_cluster_tokens(region)


# nosemgrep: guest-whitelisted-method -- verify_cargo_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_request
def register_cluster(
	region: str,
	active: bool = True,
	base_url: str = "",
	s3_endpoint: str = "",
	web_endpoint: str = "",
) -> dict:
	"""Tell Central whether a region's cluster is running, and where to reach it.

	A cluster reporting itself down sends no endpoints: it has none to offer, and the ones
	Central holds are the last known good."""
	from central.services.storage import record_cluster_status

	if active and not (base_url and s3_endpoint and web_endpoint):
		frappe.throw(
			_("A running cluster must report its admin, S3 and web endpoints."), frappe.ValidationError
		)

	return record_cluster_status(region, active, base_url, s3_endpoint, web_endpoint)


# nosemgrep: guest-whitelisted-method -- verify_cargo_bootstrapping_request authenticates the caller below.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@verify_cargo_bootstrapping_request
def request_control_credentials(base_url: str = "") -> dict:
	"""A newly installed Cargo host trades its bootstrapping token for the two it runs on.

	Issuing them is what marks the host registered: Central never calls Cargo, so this is
	the only moment it learns the host exists."""
	from central.sso import mint_cargo_access_tokens

	instance: InternalService = frappe.get_doc("Internal Service", frappe.local.cargo_instance)

	if instance.status == "Disabled":
		frappe.throw(_("This host has been disabled and cannot be registered."), frappe.AuthenticationError)

	tokens = mint_cargo_access_tokens(instance.name)
	instance.record_enrolment(base_url, tokens)

	return tokens
