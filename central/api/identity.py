from __future__ import annotations

from typing import Any

import frappe
from frappe.query_builder import Order

from central.iam import (
	get_all_capabilities,
	resolve_user_grants,
	user_has_operator_bypass,
)

# Identity and capability reads for the console. Always scoped to the signed-in
# user — safe for any logged-in member.


# --- session reads: always the signed-in user -------------------------------


@frappe.whitelist(methods=["GET"])
def my_capabilities(team: str | None = None) -> list[str]:
	"""Capabilities the signed-in user carries on a team (or any team, if omitted).
	The console gates every screen on this: reads behind `*:view`, mutations behind
	`*:manage`. Always the session user, so it is safe for any logged-in member."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	# Operators bypass team membership everywhere in Central IAM, so the console
	# must reflect that — else its gates hide screens the API would happily serve.
	if user_has_operator_bypass(user):
		return get_all_capabilities()
	grants = resolve_user_grants(user)
	team_grants = grants.get(team, []) if team else [g for gs in grants.values() for g in gs]
	return sorted({cap for grant in team_grants for cap in grant.get("caps", [])})


@frappe.whitelist(methods=["GET"])
def my_teams() -> list[dict[str, Any]]:
	"""Teams the signed-in user can switch between in the console — the teams they
	are an active member of, each with a display label + the owner email."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []

	team = frappe.qb.DocType("Team")
	member = frappe.qb.DocType("Team Member")

	rows = (
		frappe.qb.from_(member)
		.join(team)
		.on(team.name == member.parent)
		.select(team.name, team.team_name, team.owner_user)
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.user == user)
			& (member.status == "Active")
			& (team.status == "Active")
		)
		.orderby(team.team_name)
	).run(as_dict=True)

	return [
		{"name": r.name, "label": r.team_name or r.owner_user or r.name, "owner": r.owner_user} for r in rows
	]


@frappe.whitelist(methods=["GET"])
def my_invitations() -> list[dict[str, Any]]:
	"""Pending, unexpired invitations addressed to the signed-in user — the invitee's
	inbox. Each carries the inviting team's label so the console can render it without
	a second call."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []

	invitation = frappe.qb.DocType("Team Invitation")
	team = frappe.qb.DocType("Team")

	rows = (
		frappe.qb.from_(invitation)
		.left_join(team)
		.on(team.name == invitation.team)
		.select(
			invitation.name,
			invitation.team,
			invitation.role,
			invitation.invited_by,
			invitation.expires_on,
			invitation.creation,
			team.team_name,
		)
		.where(
			(invitation.email == user)
			& (invitation.status == "Pending")
			& (invitation.expires_on >= frappe.utils.today())
		)
		.orderby(invitation.creation, order=Order.desc)
	).run(as_dict=True)

	for row in rows:
		row["team_name"] = row.team_name or row.team

	return rows
