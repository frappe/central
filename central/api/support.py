from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe import _

from central import support
from central.integrations.helpdesk import HelpdeskClient, HelpdeskUnavailable
from central.utils.guards import require_support_team_member


@frappe.whitelist(methods=["POST"])
@require_support_team_member
def create_ticket(
	team: str | None = None,
	category: str = "",
	issue_type: str = "",
	subject: str = "",
	description: str = "",
	server: str | None = None,
	site: str | None = None,
	priority: str | None = None,
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
		priority=support.resolve_priority(issue_type, priority),
	)


@frappe.whitelist(methods=["GET"])
@require_support_team_member
def get_ticket_options(team: str | None = None) -> list[dict]:
	"""The categories and issues a ticket can be about."""
	return support.get_ticket_options()


@frappe.whitelist(methods=["GET"])
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
		frappe.throw(_("The support desk can't be reached right now."), HelpdeskUnavailable)

	return {"articles": articles, "tickets": tickets}


def _search_or_empty(search: Callable, *args) -> tuple[list, bool]:
	"""One failed source leaves the other visible. Both failing is a real outage."""
	try:
		return search(*args), False
	except frappe.ValidationError as error:
		frappe.log_error(title="Helpdesk related search failed", message=str(error))

		return [], True


@frappe.whitelist(methods=["GET"])
@require_support_team_member
def list_tickets(team: str | None = None) -> list[dict]:
	"""The team's open tickets, newest first."""
	return HelpdeskClient.from_settings().list_open_tickets(team=team)
