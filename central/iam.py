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


def get_user_team_names_with_capability(user: str, capability: str) -> list[str]:
	grants = resolve_user_grants(user)
	return sorted(
		team
		for team, team_grants in grants.items()
		if any(capability in grant.get("caps", []) for grant in team_grants)
	)


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


@frappe.whitelist(methods=["GET"])
def my_capabilities(team: str | None = None) -> list[str]:
	"""Capabilities the signed-in user carries on a team (or any team, if omitted).

	The single source the Central console UI gates every screen on: reads behind
	`*:view`, mutations behind `*:manage`. Always the session user — never another
	user's — so it is safe to expose to any logged-in member.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	grants = resolve_user_grants(user)
	team_grants = grants.get(team, []) if team else [g for gs in grants.values() for g in gs]
	return sorted({cap for grant in team_grants for cap in grant.get("caps", [])})


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


# ── Central console: team-roster reads ────────────────────────────────────────
# Thin, session-scoped endpoints the console's Team screens read. Visibility is
# "being a member" (any capability on the team); mutations go through the Team
# doc methods, which independently enforce team:manage_members.


def _require_team_member(team: str, user: str | None = None) -> None:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return
	if not resolve_user_grants(user).get(team):
		frappe.throw("You are not a member of this team.", frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def list_team_members(team: str) -> list[dict[str, Any]]:
	"""Roster of the team the caller belongs to (user, role, status, owner flag)."""
	_require_team_member(team)
	doc = frappe.get_doc("Team", team)
	return [
		{"user": m.user, "role": m.role, "status": m.status, "is_owner": m.user == doc.owner_user}
		for m in doc.members
	]


@frappe.whitelist(methods=["GET"])
def list_team_roles(team: str) -> list[dict[str, Any]]:
	"""System roles plus this team's custom roles, each with its capabilities."""
	_require_team_member(team)
	rows = frappe.get_all(
		"Team Role",
		filters={"is_system": 1},
		fields=["name", "role_name", "is_system", "team"],
		order_by="role_name asc",
	) + frappe.get_all(
		"Team Role",
		filters={"team": team, "is_system": 0},
		fields=["name", "role_name", "is_system", "team"],
		order_by="role_name asc",
	)
	for r in rows:
		r["capabilities"] = get_role_capabilities(r["name"])
	return rows


@frappe.whitelist(methods=["GET"])
def list_capabilities() -> list[dict[str, Any]]:
	"""Every capability in the system — the palette the role builder picks from."""
	return frappe.get_all(
		"Capability",
		fields=["name", "plane", "resource", "description"],
		order_by="name asc",
	)


# ── Central console: team-roster mutations ───────────────────────────────────
# Thin wrappers over the Team doc methods (which enforce team:manage_members) so
# the console has a uniform method-call surface.


@frappe.whitelist(methods=["POST"])
def invite_team_member(team: str, email: str, role: str, expires_in_days: int = 7) -> str:
	return frappe.get_doc("Team", team).invite_member(email, role, expires_in_days)


@frappe.whitelist(methods=["POST"])
def set_team_member_role(team: str, user: str, role: str) -> dict:
	frappe.get_doc("Team", team).set_member_role(user, role)
	return {"team": team, "user": user, "role": role}


@frappe.whitelist(methods=["POST"])
def set_team_member_status(team: str, user: str, status: str) -> dict:
	frappe.get_doc("Team", team).set_member_status(user, status)
	return {"team": team, "user": user, "status": status}


@frappe.whitelist(methods=["POST"])
def remove_team_member(team: str, user: str) -> dict:
	frappe.get_doc("Team", team).remove_member(user)
	return {"team": team, "user": user, "removed": True}


@frappe.whitelist(methods=["POST"])
def create_custom_role(team: str, role_name: str, capabilities: list | str) -> dict:
	"""Create a team-scoped custom Team Role granting exactly `capabilities`.
	Gated on team:manage_members (same authority as member changes)."""
	if not can(frappe.session.user, team, "team:manage_members"):
		frappe.throw("You can't manage roles for this team.", frappe.PermissionError)
	if isinstance(capabilities, str):
		capabilities = frappe.parse_json(capabilities)
	valid = set(get_all_capabilities())
	rows = [{"capability": c} for c in capabilities if c in valid]
	if not rows:
		frappe.throw("Pick at least one capability.", frappe.ValidationError)
	role = frappe.get_doc(
		{
			"doctype": "Team Role",
			"role_name": role_name,
			"is_system": 0,
			"team": team,
			"capabilities": rows,
		}
	).insert()
	return {"role": role.name, "role_name": role.role_name}
