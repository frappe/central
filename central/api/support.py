from __future__ import annotations

import frappe

from central.integrations.helpdesk import HelpdeskClient
from central.support import (
	build_description,
	build_subject,
	get_server,
	get_site,
	get_user_email,
	validate_ticket,
)
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
	validate_ticket(category, issue_type, description)
	server_row = get_server(team, server) if server else None
	site_row = get_site(team, site) if site else None

	return HelpdeskClient.from_settings().create_ticket(
		subject=build_subject(category, issue_type, subject),
		description=build_description(description, team, category, issue_type, server_row, site_row),
		raised_by=get_user_email(),
		priority=priority,
	)


@frappe.whitelist(methods=["GET"])
@require_support_team_member
def list_tickets(team: str | None = None) -> list[dict]:
	"""The team's open tickets, newest first."""
	return HelpdeskClient.from_settings().list_open_tickets(team=team)
