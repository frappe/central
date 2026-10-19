from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint
from frappe.utils.translations import _lt

from central.central.doctype.partner_client_link.partner_client_link import (
	ACTIVE_STATUSES,
	get_open_requests_for,
	get_request_by_token,
)
from central.central.doctype.partner_profile.partner_profile import (
	get_partner_team_by_link_hash,
	get_registration_by_token,
)
from central.iam import count_partner_staff, get_user_team_names_with_capability
from central.utils.guards import require_capability


# nosemgrep: guest-whitelisted-method -- returns a partner's display name and logo only, limited by IP.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=60, seconds=60)
def get_partner_for_link(p: str) -> dict | None:
	"""Who a partner setup link (/dashboard/partner?p=<hash of the partner's code>) is from,
	for the page's heading. A guest reads it before signing in, so it holds nothing but the
	partner team's name and logo. None for a hash no partner has."""
	partner_team = get_partner_team_by_link_hash(p)
	if not partner_team:
		return None

	team = frappe.db.get_value("Team", partner_team, ["team_name", "team_logo"], as_dict=True)
	return {"name": team.team_name, "logo": team.team_logo}


@frappe.whitelist(methods=["GET"])
def my_teams_for_partner(p: str) -> list[dict[str, Any]]:
	"""The signed-in user's teams, each saying whether it can work with the link's partner."""
	return describe_my_teams(_require_partner_team_for_link(p))


def describe_my_teams(
	partner_team: str | None = None, replaces_same_partner: bool = False
) -> list[dict[str, Any]]:
	"""The signed-in user's teams, each saying whether it can work with `partner_team`, or become
	a partner when that is None. `reason` says why one can't: it's a partner's own team, it
	already has a partner, or the user can't manage its billing. With `replaces_same_partner`, a
	team linked to `partner_team` stays available: a Connect hire takes that link over."""
	from central.api.identity import my_teams

	# A client reached through the user's own partner is not theirs to link.
	teams = [team for team in my_teams() if not team.get("via_partner")]
	names = [team["name"] for team in teams]
	manageable = set(get_user_team_names_with_capability(frappe.session.user, "billing:manage"))
	partner_teams = _get_partner_teams(names)
	links = _get_active_links(names)
	partner_names = _get_team_names([link.partner_team for link in links.values()])

	out = []
	for team in teams:
		link = links.get(team["name"])
		reason = _get_unavailable_reason(team["name"], partner_team, link, partner_teams, manageable)
		replaces = replaces_same_partner and reason == "linked_to_this_partner" and team["name"] in manageable
		out.append(
			{
				**{key: team[key] for key in ("name", "label", "logo", "role", "owner", "members")},
				"available": reason is None or replaces,
				"reason": reason,
				"current_partner": partner_names.get(link.partner_team) if link else None,
			}
		)
	return out


@frappe.whitelist(methods=["POST"])
@require_capability("billing:manage", _lt("Only the account's owner or an admin can add a partner."))
def request_partner_link(team: str, p: str, paid_by_partner: int | bool = 0) -> dict[str, Any]:
	"""The customer's request to work with the partner whose code link they opened: a
	Requested Partner Client Link for the partner to answer."""
	link = frappe.get_doc(
		{
			"doctype": "Partner Client Link",
			"partner_team": _require_partner_team_for_link(p),
			"client_team": team,
			"source": "Partner Code",
			"status": "Requested",
			"paid_by_partner": cint(paid_by_partner),
		}
	).insert()
	return {"name": link.name, "status": link.status, "paid_by_partner": link.paid_by_partner}


# nosemgrep: guest-whitelisted-method -- the random emailed token is the key, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
def get_partner_registration(token: str) -> dict[str, Any]:
	"""The registration behind the link Connect emailed to a partner's owner."""
	return get_registration_by_token(token).get_summary()


@frappe.whitelist(methods=["GET"])
def my_teams_for_registration() -> list[dict[str, Any]]:
	"""The signed-in user's teams, each saying whether it can become a partner."""
	return describe_my_teams()


@frappe.whitelist(methods=["POST"])
def complete_partner_registration(token: str, team: str) -> dict[str, Any]:
	return get_registration_by_token(token).complete(team)


# nosemgrep: guest-whitelisted-method -- the random token from Connect is the key, and the IP rate limit applies.
@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(limit=30, seconds=60, methods="GET")
def get_partner_request(token: str) -> dict[str, Any]:
	"""The request behind a customer's setup link from Connect."""
	return get_request_by_token(token).get_summary()


@frappe.whitelist(methods=["GET"])
def my_partner_requests() -> list[dict[str, Any]]:
	"""The partners waiting for the signed-in user's answer, each with the teams that can accept it."""
	requests = []
	for name in get_open_requests_for(frappe.session.user):
		link = frappe.get_doc("Partner Client Link", name)
		requests.append(
			{**link.get_summary(), "teams": describe_my_teams(link.partner_team, replaces_same_partner=True)}
		)
	return requests


@frappe.whitelist(methods=["POST"])
def accept_partner_request(
	request: str, team: str, paid_by_partner: int | bool = 0, partner_access: int | bool = 0
) -> dict[str, Any]:
	"""The customer picks the account the partner they hired on Connect works on."""
	link = frappe.get_doc("Partner Client Link", request)
	link.accept(team, paid_by_partner, partner_access)
	return {
		"name": link.name,
		"status": link.status,
		"team": link.client_team,
		"partner_access": link.partner_access,
		"return_url": link.return_url,
	}


@frappe.whitelist(methods=["GET"])
@require_capability("billing:view", _lt("Only members who can see billing can see the team's partners."))
def get_team_partners(team: str) -> dict[str, Any]:
	"""The team's partner, and its clients when the team is a partner."""
	links = frappe.get_list(
		"Partner Client Link",
		filters={"status": ["in", ACTIVE_STATUSES]},
		or_filters={"client_team": team, "partner_team": team},
		fields=[
			"name",
			"partner_team",
			"partner_team_name",
			"client_team",
			"client_team_name",
			"customer_email",
			"project_title",
			"status",
			"source",
			"paid_by_partner",
			"partner_access",
			"creation",
		],
		order_by="creation desc",
	)
	partner = next((link for link in links if link.client_team == team), None)
	return {
		# A system read: whether the team is a partner, and nothing of its profile.
		"is_partner": bool(frappe.db.exists("Partner Profile", {"team": team, "status": "Completed"})),
		"partner": _describe_partner(partner) if partner else None,
		"clients": [_describe_link(link) for link in links if link.partner_team == team],
	}


@frappe.whitelist(methods=["POST"])
@require_capability("billing:manage", _lt("Only the team's owner or an admin can end a partner link."))
def end_team_partner_link(team: str, link: str, reason: str | None = None) -> dict[str, Any]:
	"""The customer removes its partner, or the partner stops working with a customer."""
	doc = frappe.get_doc("Partner Client Link", link)
	doc.end_for_team(team, reason)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
@require_capability("billing:manage", _lt("Only the team's owner or an admin can change a partner's access."))
def set_team_partner_access(team: str, link: str, partner_access: int | bool) -> dict[str, Any]:
	"""The customer gives its partner access, or takes it away."""
	doc = frappe.get_doc("Partner Client Link", link)
	doc.set_partner_access(team, partner_access)
	return {"name": doc.name, "partner_access": doc.partner_access}


def _describe_partner(link) -> dict[str, Any]:
	# The partner's logo, as the guest-readable link heading shows it.
	return {
		**_describe_link(link),
		"partner_logo": frappe.db.get_value("Team", link.partner_team, "team_logo"),
		"staff_count": count_partner_staff(link.partner_team) if link.partner_access else 0,
	}


def _describe_link(link) -> dict[str, Any]:
	return {
		"name": link.name,
		"partner_name": link.partner_team_name,
		"client_name": link.client_team_name or link.customer_email or link.client_team,
		"project_title": link.project_title,
		"status": link.status,
		"source": link.source,
		"paid_by_partner": bool(link.paid_by_partner),
		"partner_access": bool(link.partner_access),
		"since": link.creation,
	}


def _require_partner_team_for_link(p: str | None) -> str:
	partner_team = get_partner_team_by_link_hash(p)
	if not partner_team:
		frappe.throw(_("This link isn't valid. Ask your partner for a new one."), frappe.DoesNotExistError)
	return partner_team


def _get_unavailable_reason(
	team: str, partner_team: str | None, link, partner_teams: set[str], manageable: set[str]
) -> str | None:
	if team in partner_teams:
		return "partner_team"
	if link:
		return "linked_to_this_partner" if link.partner_team == partner_team else "linked_to_another_partner"
	if team not in manageable:
		return "cannot_manage"
	return None


def _get_partner_teams(teams: list[str]) -> set[str]:
	# A system read: Partner Profile holds partner codes, so only operators read it directly.
	# This says which of the user's own teams are partners, and nothing else.
	return set(frappe.get_all("Partner Profile", filters={"team": ["in", teams]}, pluck="team"))


def _get_active_links(teams: list[str]) -> dict[str, Any]:
	"""The active link of each team, as far as the user may see it. A user who can't view a
	team's billing doesn't see its link, and that team is refused as `cannot_manage`."""
	links = frappe.get_list(
		"Partner Client Link",
		filters={"client_team": ["in", teams], "status": ["in", ACTIVE_STATUSES]},
		fields=["client_team", "partner_team"],
	)
	return {link.client_team: link for link in links}


def _get_team_names(teams: list[str]) -> dict[str, str]:
	# A system read: the partner's team isn't the user's, and only its display name is shown,
	# the same name the guest-readable link heading shows.
	return dict(
		frappe.get_all("Team", filters={"name": ["in", teams]}, fields=["name", "team_name"], as_list=True)
	)
