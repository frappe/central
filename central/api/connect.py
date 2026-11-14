import frappe

from central.identity.doctype.partner_registration.partner_registration import PartnerRegistration

CONNECT_INTEGRATION_ROLE = "Connect Integration"


@frappe.whitelist(methods=["POST"])
def register_partner(
	connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
) -> dict:
	"""Ask the owner of a Connect partner to choose the team that represents the partner."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return PartnerRegistration.request(connect_partner_id, partner_name, owner_email, return_url)


@frappe.whitelist(methods=["POST"])
def get_partner_registration(connect_partner_id: str) -> dict:
	"""The state of a partner's registration, with its team and partner code once Completed."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return PartnerRegistration.get_status(connect_partner_id)
