from __future__ import annotations

import frappe

from central.iam import (
	can,
	get_user_team_names,
	get_user_team_names_with_capability,
	resolve_resource_scope,
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


# The Manage Roles dialog scopes a grant to resource_type "Server" (an Asset) or
# "Site"; the Team Member's resource_name holds that doc's name. So the Asset list
# is scoped by "Server" grants, the Site list by "Site" grants.


def asset_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Asset", "Server", "server:view", user)


def asset_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, "Server", ("server:view",), (), user, ptype)


def site_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Site", "Site", "server:view", user)


def site_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, "Site", ("server:view",), (), user, ptype)


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


def _team_field_query_conditions(
	doctype: str, resource_type: str, capability: str, user: str | None = None
) -> str:
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""

	# Per team: either the whole team (an all-resources grant with the cap) or just
	# the specific rows an explicit scoped grant names.
	scope = resolve_resource_scope(user, capability, resource_type)
	if not scope:
		return "1 = 0"

	clauses = []
	for team, allowed in scope.items():
		team_sql = frappe.db.escape(team)
		if allowed == "*":
			clauses.append(f"`tab{doctype}`.`team` = {team_sql}")
		else:
			names = ", ".join(frappe.db.escape(name) for name in sorted(allowed))
			clauses.append(f"(`tab{doctype}`.`team` = {team_sql} and `tab{doctype}`.`name` in ({names}))")
	return f"({' or '.join(clauses)})"


def _team_field_has_permission(
	doc,
	resource_type: str,
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

	capabilities = write_capabilities if ptype in MUTATING_PERMISSION_TYPES else read_capabilities
	# Gate on this exact resource: a grant scoped to another server/site must not
	# authorize it, and an all-resources grant covers it.
	return any(can(user, team, capability, resource_type, doc.name) for capability in capabilities)
