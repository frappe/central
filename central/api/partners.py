import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils.translations import _lt

from central.billing.doctype.billing_profile.billing_profile import get_team_currency
from central.iam import PARTNER_CAPABILITY, can
from central.identity.doctype.team.partner import (
	complete_registration,
	get_customer_hosting,
	get_registration_summary,
)
from central.partners.doctype.partner_link.partner_link import (
	LINK_FIELDS,
	PartnerLink,
	get_partner_team_by_code,
	summarize_links,
)
from central.utils.guards import require_capability

MANAGE_PARTNERS_REFUSAL = _lt(
	"You can't manage partners for this team. Ask a team admin to review your access."
)
CUSTOMERS_REFUSAL = _lt("You can't see this team's customers. Ask a team admin to review your access.")


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
	"""The customer team's Active partner link, or None. `partner_currency` is the currency the
	partner pays in, which the customer sees before asking the partner to pay."""
	links = frappe.get_list(
		"Partner Link", filters={"customer_team": team, "status": "Active"}, fields=LINK_FIELDS, limit=1
	)
	if not links:
		return None

	summary = summarize_links(links)[0]
	return {**summary, "partner_currency": get_team_currency(summary["partner_team"])}


@frappe.whitelist(methods=["GET"])
def get_team_customers(team: str) -> dict:
	"""The partner team's code, the currency it pays in, and its customer links, the newest
	first. Each Active customer has its MRR and servers, and whether the caller can open it."""
	user = frappe.session.user
	if not (can(user, team, "team:manage_partners") or can(user, team, PARTNER_CAPABILITY)):
		frappe.throw(str(CUSTOMERS_REFUSAL), frappe.PermissionError)

	links = summarize_links(
		frappe.get_list(
			"Partner Link", filters={"partner_team": team}, fields=LINK_FIELDS, order_by="linked_on desc"
		)
	)
	hosting = get_customer_hosting([link["customer_team"] for link in links if link["status"] == "Active"])
	for link in links:
		customer = hosting.get(link["customer_team"]) if link["status"] == "Active" else None
		link["currency"] = customer["currency"] if customer else None
		link["mrr"] = customer["mrr"] if customer else None
		link["server_count"] = len(customer["servers"]) if customer else None
		link["can_open"] = bool(customer) and can(user, link["customer_team"], "server:view")

	return {
		"partner_code": frappe.db.get_value("Team", team, "partner_code"),
		"currency": get_team_currency(team),
		"customers": links,
	}


@frappe.whitelist(methods=["POST"])
def end_partner_link(link: str, reason: str) -> dict:
	"""End a link from either side. The link's permission rules decide who may."""
	doc = frappe.get_doc("Partner Link", link)
	# An ended link returns before save, so the check cannot wait for save to run it.
	doc.check_permission("write")
	doc.end(reason)
	return doc.get_summary()


@frappe.whitelist(methods=["POST"])
def set_partner_role(link: str, role: str) -> dict:
	"""Change what the partner can do in the customer team: Viewer or Developer."""
	doc = frappe.get_doc("Partner Link", link)
	doc.set_role(role)
	return doc.get_summary()


@frappe.whitelist(methods=["POST"])
def set_partner_payer(link: str, payer: str) -> dict:
	"""Change who pays: the customer asks, the partner accepts, or either side declines or stops.
	The link's rules decide who may make each change."""
	doc = frappe.get_doc("Partner Link", link)
	doc.set_payer(payer)
	return doc.get_summary()
