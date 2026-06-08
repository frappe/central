from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe


OPERATOR_BYPASS_ROLE = "System Manager"


def user_has_operator_bypass(user: str | None = None) -> bool:
	"""The only non-team-membership bypass in Central IAM."""
	user = user or frappe.session.user
	return OPERATOR_BYPASS_ROLE in frappe.get_roles(user)


def get_all_capabilities() -> list[str]:
	return frappe.get_all("Capability", pluck="name", order_by="name")


def get_role_capabilities(role: str) -> list[str]:
	return frappe.get_all(
		"Role Capability",
		filters={"parent": role, "parenttype": "Team Role", "parentfield": "capabilities"},
		pluck="capability",
		order_by="idx asc",
	)


def get_user_team_names(user: str) -> list[str]:
	team = frappe.qb.DocType("Team")
	member = frappe.qb.DocType("Team Member")

	rows = (
		frappe.qb.from_(member)
		.join(team)
		.on(team.name == member.parent)
		.select(team.name)
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.user == user)
			& (member.status == "Active")
			& (team.status == "Active")
		)
		.orderby(team.name)
	).run(as_dict=True)

	return [row.name for row in rows]


def _get_membership_capability_rows(user: str) -> list[dict[str, Any]]:
	team = frappe.qb.DocType("Team")
	member = frappe.qb.DocType("Team Member")
	team_role = frappe.qb.DocType("Team Role")
	role_capability = frappe.qb.DocType("Role Capability")

	return (
		frappe.qb.from_(member)
		.join(team)
		.on(team.name == member.parent)
		.join(team_role)
		.on(team_role.name == member.role)
		.join(role_capability)
		.on(
			(role_capability.parent == team_role.name)
			& (role_capability.parenttype == "Team Role")
			& (role_capability.parentfield == "capabilities")
		)
		.select(
			team.name.as_("team"),
			member.role,
			team_role.is_system,
			team_role.team.as_("role_team"),
			role_capability.capability,
		)
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.user == user)
			& (member.status == "Active")
			& (team.status == "Active")
		)
		.orderby(team.name, member.idx, role_capability.idx)
	).run(as_dict=True)


def resolve_user_grants(user: str) -> dict[str, list[dict[str, Any]]]:
	"""Resolve Team Member -> Team Role -> Capability into token-ready grants."""
	grants_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)

	if user_has_operator_bypass(user):
		caps = get_all_capabilities()
		for team in frappe.get_all("Team", filters={"status": "Active"}, pluck="name", order_by="name"):
			grants_by_team[team].append(
				{
					"role": OPERATOR_BYPASS_ROLE,
					"source": "operator",
					"scope": "*",
					"caps": caps,
				}
		)
		return dict(grants_by_team)

	grants_by_key = {}
	for row in _get_membership_capability_rows(user):
		if not row.is_system and row.role_team != row.team:
			continue

		key = (row.team, row.role)
		if key not in grants_by_key:
			grants_by_key[key] = {
				"role": row.role,
				"source": "member",
				"scope": "*",
				"caps": [],
			}
			grants_by_team[row.team].append(grants_by_key[key])

		if row.capability not in grants_by_key[key]["caps"]:
			grants_by_key[key]["caps"].append(row.capability)

	return dict(grants_by_team)


def get_fc_teams_claim(user: str | None = None) -> dict[str, list[dict[str, Any]]]:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return {}
	return resolve_user_grants(user)


def can(user: str, team: str, capability: str) -> bool:
	if not frappe.db.exists("Capability", capability):
		return False
	if not frappe.db.exists("Team", {"name": team, "status": "Active"}):
		return False
	if user_has_operator_bypass(user):
		return True

	for grant in resolve_user_grants(user).get(team, []):
		if capability in grant.get("caps", []):
			return True

	return False


def get_effective_permissions(user: str, team: str | None = None) -> dict[str, Any]:
	grants = resolve_user_grants(user)
	if team:
		grants = {team: grants.get(team, [])}

	effective = {}
	for team_name, team_grants in grants.items():
		caps = sorted({cap for grant in team_grants for cap in grant.get("caps", [])})
		effective[team_name] = {"caps": caps, "grants": team_grants}

	return {"user": user, "teams": effective}
