from __future__ import annotations

from typing import Any

import frappe

from central.iam import (
	can,
	expand_capabilities,
	get_all_capabilities,
	get_role_capabilities,
	resolve_user_grants,
	user_has_operator_bypass,
)

# Team-roster reads + role management for the console's Team screens. Visibility
# is "being a member" (any capability on the team); mutations delegate to the Team
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
	picked = [c for c in capabilities if c in valid]
	if not picked:
		frappe.throw("Pick at least one capability.", frappe.ValidationError)
	# Persist the implied dependencies too (e.g. site:create pulls in site:view +
	# server:view), so the saved role is usable and matches what enforcement grants.
	rows = [{"capability": c} for c in expand_capabilities(picked) if c in valid]
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
