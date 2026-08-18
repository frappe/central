from __future__ import annotations

import frappe

from central.iam import (
	can,
	get_user_team_names,
	get_user_team_names_with_capability,
	user_has_operator_bypass,
)

MUTATING_PERMISSION_TYPES = {"create", "write", "delete", "submit", "cancel", "amend"}


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


def asset_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Asset", "server:view", user)


def asset_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def resource_action_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Resource Action", "server:view", user)


def resource_action_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	# Read needs server:view; opening an action needs any server-mutating capability on the
	# team (the endpoint additionally gates the specific action). Outcomes are written by the
	# Atlas webhook / sweep, not the portal, so tenants get no write/delete here.
	return _team_field_has_permission(
		doc, ("server:view",), ("server:create", "server:power", "server:terminate"), user, ptype
	)


def site_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Site", "server:view", user)


def site_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def iam_permission_probe_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""
	return f"`tabIAM Permission Probe`.`user` = {frappe.db.escape(user)}"


def iam_permission_probe_has_permission(
	doc, user: str | None = None, ptype: str | None = None, **kwargs
) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	return doc.user == user


def _team_field_query_conditions(doctype: str, capability: str, user: str | None = None) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""

	teams = get_user_team_names_with_capability(user, capability)
	if not teams:
		return "1 = 0"

	escaped = ", ".join(frappe.db.escape(team) for team in teams)
	return f"`tab{doctype}`.`team` in ({escaped})"


def _team_field_has_permission(
	doc,
	read_capabilities: tuple[str, ...],
	write_capabilities: tuple[str, ...],
	user: str | None = None,
	ptype: str | None = None,
) -> bool:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True

	team = getattr(doc, "team", None)
	if not team:
		return False

	if ptype in MUTATING_PERMISSION_TYPES:
		return _can_any(user, team, write_capabilities)

	return _can_any(user, team, read_capabilities)


def _can_any(user: str, team: str, capabilities: tuple[str, ...]) -> bool:
	return any(can(user, team, capability) for capability in capabilities)
