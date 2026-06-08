from __future__ import annotations

import frappe

from central.iam import get_user_team_names, user_has_operator_bypass


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


def team_has_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
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


def team_role_has_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	return bool(doc.is_system) or doc.team in get_user_team_names(user)
