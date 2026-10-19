from typing import Any

import frappe
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import escape_html

from central.iam import (
	CLIENTS_SCOPE,
	PARTNER_ROLE,
	get_all_capabilities,
	resolve_user_grants,
	user_has_operator_bypass,
)


@frappe.whitelist(methods=["GET"])
def my_capabilities(team: str | None = None) -> list[str]:
	"""The capabilities the session user holds on a team, or on any team when none is given.
	A server capability is listed when the user holds it on any server; each server row
	carries its own list."""
	user = frappe.session.user
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
	are an active member of, each with a display label, the owner email, the
	caller's own role, how many people are in it, when it was created, and the
	onboarding steps the caller still has to answer as its owner, and whether it is a
	partner. A partner's staff member also gets the clients they can act on, with
	`via_partner` naming the partner."""
	user = frappe.session.user

	team = frappe.qb.DocType("Team")
	member = frappe.qb.DocType("Team Member")

	rows = (
		frappe.qb.from_(member)
		.join(team)
		.on(team.name == member.parent)
		.select(team.name, team.team_name, team.team_logo, team.owner_user, team.creation, member.role)
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.user == user)
			& (member.status == "Active")
			& (member.resource_type != CLIENTS_SCOPE)
			& (team.status == "Active")
		)
		.orderby(team.team_name)
	).run(as_dict=True)

	# One row per role grant, so a member holding two roles in a team lands here
	# twice. Fold to one entry per team, keeping the strongest role.
	teams: dict[str, dict[str, Any]] = {}
	for r in rows:
		entry = teams.setdefault(
			r.name,
			{
				"name": r.name,
				"label": r.team_name or r.owner_user or r.name,
				"logo": r.team_logo,
				"owner": r.owner_user,
				"role": r.role,
				"members": 0,
				"created": r.creation,
				"via_partner": None,
				"is_partner": False,
			},
		)
		if _role_rank(r.role) < _role_rank(entry["role"]):
			entry["role"] = r.role

	_add_client_teams(teams, user)
	if not teams:
		return []

	counts = (
		frappe.qb.from_(member)
		.select(member.parent, Count(member.user).distinct().as_("members"))
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.status == "Active")
			& member.parent.isin(list(teams))
		)
		.groupby(member.parent)
	).run(as_dict=True)
	for row in counts:
		teams[row.parent]["members"] = row.members

	_mark_partner_teams(teams)

	for entry in teams.values():
		entry["onboarding"] = []
	owned_teams = [name for name, entry in teams.items() if entry["owner"] == user]
	for row in _pending_onboarding_steps(owned_teams):
		teams[row.parent]["onboarding"].append(row.step)

	return list(teams.values())


def _mark_partner_teams(teams: dict[str, dict[str, Any]]) -> None:
	# A system read: which of these teams are partners, and nothing of their profiles.
	for partner_team in frappe.get_all(
		"Partner Profile", filters={"team": ["in", list(teams)], "status": "Completed"}, pluck="team"
	):
		teams[partner_team]["is_partner"] = True


def _add_client_teams(teams: dict[str, dict[str, Any]], user: str) -> None:
	"""The clients a partner's staff member reaches through their Client access. The user is
	not a member of them, so they hold the Partner role there and answer no onboarding."""
	partner_of = {
		team: grant["partner_team"]
		for team, grants in resolve_user_grants(user).items()
		for grant in grants
		if grant["source"] == "partner" and team not in teams
	}
	if not partner_of:
		return

	# A system read: the user reaches these teams through their partner, not as a member.
	clients = frappe.get_all(
		"Team",
		filters={"name": ["in", list(partner_of)]},
		fields=["name", "team_name", "team_logo", "owner_user", "creation"],
	)
	partner_names = dict(
		frappe.get_all(
			"Team",
			filters={"name": ["in", list(set(partner_of.values()))]},
			fields=["name", "team_name"],
			as_list=True,
		)
	)
	for row in clients:
		teams[row.name] = {
			"name": row.name,
			"label": row.team_name or row.owner_user or row.name,
			"logo": row.team_logo,
			"owner": row.owner_user,
			"role": PARTNER_ROLE,
			"members": 0,
			"created": row.creation,
			"via_partner": partner_names.get(partner_of[row.name]),
			"is_partner": False,
		}


def _pending_onboarding_steps(teams: list[str]) -> list[dict[str, Any]]:
	if not teams:
		return []

	step = frappe.qb.DocType("Team Onboarding Step")

	return (
		frappe.qb.from_(step)
		.select(step.parent, step.step)
		.where(
			(step.parenttype == "Team")
			& (step.parentfield == "onboarding_steps")
			& (step.status == "Pending")
			& step.parent.isin(teams)
		)
		.orderby(step.idx)
	).run(as_dict=True)


# Owner outranks Admin, and any named role outranks none.
_ROLE_ORDER = ["Owner", "Admin"]


def _role_rank(role: str | None) -> int:
	if role in _ROLE_ORDER:
		return _ROLE_ORDER.index(role)
	return len(_ROLE_ORDER)


@frappe.whitelist(methods=["GET"])
def my_invitations() -> list[dict[str, Any]]:
	"""Pending, unexpired invitations addressed to the signed-in user — the invitee's
	inbox. Each carries the inviting team's label so the console can render it without
	a second call."""
	user = frappe.session.user

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


@frappe.whitelist(methods=["GET"])
def my_profile() -> dict[str, Any]:
	"""The signed-in user's own profile — email, display name, photo."""
	user = frappe.session.user
	row = frappe.db.get_value("User", user, ["full_name", "user_image"], as_dict=True)

	return {"user": user, "full_name": row.full_name, "user_image": row.user_image}


@frappe.whitelist(methods=["POST"])
def update_profile(full_name: str) -> dict[str, Any]:
	"""Update the signed-in user's display name. Only ever operates on the
	session user — there is no user parameter to abuse. The whole string goes
	into first_name (frappe recomputes full_name from the parts)."""
	user = frappe.session.user
	doc = frappe.get_doc("User", user)
	# Escaped at write time, matching the signup path (central.users.create_user):
	# full_name reaches HTML contexts outside this SPA (frappe emails, desk).
	doc.first_name = escape_html(full_name.strip())
	doc.middle_name = None
	doc.last_name = None
	# The only target is the session user, so this writes nothing but the caller's own name.
	doc.save(ignore_permissions=True)

	return {"full_name": doc.full_name}


@frappe.whitelist(methods=["POST"])
def set_profile_photo(file_url: str | None = None) -> dict[str, Any]:
	"""Set the signed-in user's photo to an uploaded image, or clear it."""
	user = frappe.session.user
	doc = frappe.get_doc("User", user)
	doc.user_image = file_url or None
	doc.save()

	return {"user_image": doc.user_image}
