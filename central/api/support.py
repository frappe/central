from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from central import support
from central.integrations.helpdesk import HelpdeskClient, HelpdeskUnavailable
from central.utils.guards import require_support_team_member


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60, ip_based=False, user_based=True)
@require_support_team_member
def create_ticket(
	team: str | None = None,
	category: str = "",
	issue_type: str = "",
	subject: str = "",
	description: str = "",
	server: str | None = None,
	site: str | None = None,
) -> dict:
	"""Open a support ticket for the caller's team.
	A `server` or `site` is checked against the team first, then attached as context."""
	support.validate_ticket(category, issue_type, description)
	server_row = support.get_server(team, server) if server else None
	site_row = support.get_site(team, site) if site else None

	return HelpdeskClient.from_settings().create_ticket(
		subject=support.build_subject(category, issue_type, subject),
		description=support.build_description(description, team, category, issue_type, server_row, site_row),
		raised_by=support.get_user_email(),
		priority=support.resolve_priority(issue_type),
	)


@frappe.whitelist(methods=["GET"])
@require_support_team_member
def get_ticket_options(team: str | None = None) -> list[dict]:
	"""The categories and issues a ticket can be about."""
	return support.get_ticket_options()


@frappe.whitelist(methods=["GET"])
@rate_limit(limit=60, seconds=60, ip_based=False, user_based=True)
@require_support_team_member
def find_related(team: str | None = None, query: str = "") -> dict:
	"""Articles and the team's past tickets that match `query`, before a ticket is opened.
	A query shorter than 3 characters skips Helpdesk, because it matches everything."""
	query = query.strip()
	if len(query) < 3:
		return {"articles": [], "tickets": []}

	client = HelpdeskClient.from_settings()
	if support.is_articles_enabled():
		articles, articles_failed = _search_or_empty(client.search_articles, query)
	else:
		articles, articles_failed = [], False
	tickets, tickets_failed = _search_or_empty(client.list_related_tickets, team, query)
	if articles_failed and tickets_failed:
		frappe.throw(_("Support is unavailable right now. Try again in a few minutes."), HelpdeskUnavailable)

	return {"articles": articles, "tickets": support.keep_own_ticket_links(tickets)}


def _search_or_empty(search: Callable, *args) -> tuple[list, bool]:
	"""One failed source leaves the other visible. Both failing is a real outage.
	The Helpdesk client has already logged the failure."""
	try:
		return search(*args), False
	except frappe.ValidationError:
		return [], True


@frappe.whitelist(methods=["GET"])
@require_support_team_member
def list_tickets(team: str | None = None) -> list[dict]:
	"""The team's open tickets, newest first. Only the caller's own tickets link to the portal."""
	return support.keep_own_ticket_links(HelpdeskClient.from_settings().list_open_tickets(team=team))
