from __future__ import annotations

import frappe

from central.iam import (
	can,
	get_user_team_names,
	get_user_team_names_with_capability,
	user_has_operator_bypass,
)


def _team_filter(user: str) -> str:
	teams = get_user_team_names(user)
	if not teams:
		return "1 = 0"
	escaped = ", ".join(frappe.db.escape(team) for team in teams)
	return f"`tabTeam`.`name` in ({escaped})"


def team_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""
	return _team_filter(user)


def team_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	if ptype == "create":
		return True
	if ptype == "write":
		return can(user, doc.name, "team:edit") or can(user, doc.name, "team:manage_members")
	if ptype == "delete":
		return can(user, doc.name, "team:delete")
	return doc.name in get_user_team_names(user)


def team_role_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""

	teams = get_user_team_names(user)
	if not teams:
		return "`tabTeam Role`.`is_system` = 1"

	escaped = ", ".join(frappe.db.escape(team) for team in teams)
	return f"(`tabTeam Role`.`is_system` = 1 or `tabTeam Role`.`team` in ({escaped}))"


def team_role_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	return bool(doc.is_system) or doc.team in get_user_team_names(user)


def team_invitation_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""

	conditions = [f"`tabTeam Invitation`.`email` = {frappe.db.escape(user)}"]
	teams = get_user_team_names_with_capability(user, "team:manage_members")
	if teams:
		escaped = ", ".join(frappe.db.escape(team) for team in teams)
		conditions.append(f"`tabTeam Invitation`.`team` in ({escaped})")
	return f"({' or '.join(conditions)})"


def team_invitation_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	if ptype == "create":
		return can(user, doc.team, "team:manage_members")
	return doc.email == user or can(user, doc.team, "team:manage_members")
