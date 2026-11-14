import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils.translations import _lt

from central.identity.doctype.partner_link.partner_link import (
	LINK_FIELDS,
	PartnerLink,
	get_partner_team_by_code,
	summarize_links,
)
from central.identity.doctype.team.partner import complete_registration, get_registration_summary
from central.utils.guards import require_capability

MANAGE_PARTNERS_REFUSAL = _lt(
	"You can't manage partners for this team. Ask a team admin to review your access."
)


# nosemgrep: guest-whitelisted-method -- the random token from Connect is the key, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
def get_partner_registration(token: str) -> dict:
	"""The partner registration behind a link from Frappe Connect."""
	return get_registration_summary(token)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60, methods="POST")
def complete_partner_registration(token: str, team: str) -> dict:
	"""Make one of the caller's teams the partner's team."""
	return complete_registration(token, team)


@frappe.whitelist(methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
@require_capability("team:manage_partners", MANAGE_PARTNERS_REFUSAL)
def get_partner_by_code(team: str, code: str) -> dict:
	"""The partner a code names, so the customer can check it before they add it."""
	partner = frappe.db.get_value(
		"Team", get_partner_team_by_code(code), ["team_name", "team_logo"], as_dict=True
	)
	return {"partner_name": partner.team_name, "partner_logo": partner.team_logo}


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60, methods="POST")
@require_capability("team:manage_partners", MANAGE_PARTNERS_REFUSAL)
def add_partner(team: str, code: str, reference: str | None = None) -> dict:
	"""Add the partner that owns `code` to `team`. `reference` comes from a Connect link."""
	return PartnerLink.add(team, code, reference).get_summary()


@frappe.whitelist(methods=["GET"])
@require_capability("team:manage_partners", MANAGE_PARTNERS_REFUSAL)
def get_team_partner(team: str) -> dict | None:
	"""The customer team's Active partner link, or None."""
	links = frappe.get_list(
		"Partner Link", filters={"customer_team": team, "status": "Active"}, fields=LINK_FIELDS, limit=1
	)
	return summarize_links(links)[0] if links else None


@frappe.whitelist(methods=["GET"])
@require_capability("team:manage_partners", MANAGE_PARTNERS_REFUSAL)
def get_team_customers(team: str) -> dict:
	"""The partner team's code and its customer links, the newest first."""
	links = frappe.get_list(
		"Partner Link", filters={"partner_team": team}, fields=LINK_FIELDS, order_by="linked_on desc"
	)
	return {
		"partner_code": frappe.db.get_value("Team", team, "partner_code"),
		"customers": summarize_links(links),
	}


@frappe.whitelist(methods=["POST"])
def end_partner_link(link: str, reason: str) -> dict:
	"""End a link from either side. The link's permission rules decide who may."""
	doc = frappe.get_doc("Partner Link", link)
	# An ended link returns before save, so the check cannot wait for save to run it.
	doc.check_permission("write")
	doc.end(reason)
	return doc.get_summary()
