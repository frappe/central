from __future__ import annotations

import frappe

from central.central.doctype.partner_client_link.partner_client_link import (
	get_connect_link,
	request_connect_link,
)
from central.central.doctype.partner_profile.partner_profile import (
	get_connect_registration,
	register_connect_partner,
)
from central.users import CONNECT_INTEGRATION_ROLE


@frappe.whitelist(methods=["POST"])
def register_partner(
	connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
) -> dict:
	"""Ask a partner's owner to pick the Central team that is the partner."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return register_connect_partner(connect_partner_id, partner_name, owner_email, return_url)


@frappe.whitelist(methods=["POST"])
def get_partner_registration(connect_partner_id: str) -> dict:
	"""Whether the partner's owner has picked its Central team. It never issues a new link."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return get_connect_registration(connect_partner_id)


@frappe.whitelist(methods=["POST"])
def create_partner_link(
	connect_partner_id: str, engagement_id: str, customer_email: str, project_title: str, return_url: str
) -> dict:
	"""Ask the customer who hired a partner on Connect to accept the partner on Central."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return request_connect_link(connect_partner_id, engagement_id, customer_email, project_title, return_url)


@frappe.whitelist(methods=["POST"])
def get_partner_link(engagement_id: str) -> dict:
	"""Where the link for a Connect project stands."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	link = get_connect_link(engagement_id)
	return {
		"status": "Expired" if link.status == "Requested" and not link.is_open() else link.status,
		"customer_team": link.client_team,
		"ended_by": link.ended_by,
		"ended_on": link.ended_on,
	}


@frappe.whitelist(methods=["POST"])
def end_partner_link(engagement_id: str, reason: str | None = None) -> dict:
	"""End the link when the Connect project ends or is cancelled."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	link = get_connect_link(engagement_id)
	link.end(reason)
	return {"status": link.status}
