import frappe
from frappe import _
from frappe.utils import get_datetime

from central.identity.doctype.partner_link.partner_link import LINK_FIELDS, summarize_links
from central.identity.doctype.team.partner import (
	get_customer_hosting,
	get_partner_team,
	get_registration_status,
	request_registration,
)

CONNECT_INTEGRATION_ROLE = "Connect Integration"


@frappe.whitelist(methods=["POST"])
def register_partner(
	connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
) -> dict:
	"""Ask the owner of a Connect partner to choose the team that represents the partner."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return request_registration(connect_partner_id, partner_name, owner_email, return_url)


@frappe.whitelist(methods=["POST"])
def get_partner_registration(connect_partner_id: str) -> dict:
	"""Whether a team represents the partner, with the team and its partner code once it does."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	return get_registration_status(connect_partner_id)


@frappe.whitelist(methods=["POST"])
def get_partner_customers(connect_partner_id: str, modified_after: str | None = None) -> list[dict]:
	"""The links of one registered partner, the newest first. `modified_after` limits the list to
	links that changed after that datetime."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	team = get_partner_team(connect_partner_id)
	if not team:
		frappe.throw(_("Partner {0} is not registered on Frappe Cloud.").format(connect_partner_id))

	filters = {"partner_team": team.name}
	if modified_after:
		filters["modified"] = (">", get_datetime(modified_after))
	# The integration user is in no team; only_for above is its only gate.
	links = frappe.get_all("Partner Link", filters=filters, fields=LINK_FIELDS, order_by="linked_on desc")
	hosting = get_customer_hosting([link.customer_team for link in links if link.status == "Active"])

	return [
		_to_connect_row(link, hosting.get(link["customer_team"]) if link["status"] == "Active" else None)
		for link in summarize_links(links)
	]


@frappe.whitelist(methods=["POST"])
def end_partner_link(link: str, reason: str) -> dict:
	"""End a link for Connect. Ending a link that has ended changes nothing."""
	frappe.only_for(CONNECT_INTEGRATION_ROLE)
	doc = frappe.get_doc("Partner Link", link)
	# The integration user is in neither team; only_for above is its gate.
	doc.flags.ignore_permissions = True
	doc.end(reason)
	return {"status": doc.status}


def _to_connect_row(link: dict, hosting: dict | None) -> dict:
	"""An ended link has no hosting: the partner no longer sees the customer's servers."""
	hosting = hosting or {"currency": None, "mrr": 0.0, "servers": []}
	return {
		"link": link["name"],
		"reference": link["reference"],
		"status": link["status"],
		"role": link["role"],
		"customer_team": link["customer_team"],
		"customer_team_name": link["customer_name"],
		"customer_email": link["customer_email"],
		"linked_on": link["linked_on"],
		"ended_on": link["ended_on"],
		**hosting,
	}
