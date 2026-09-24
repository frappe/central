from __future__ import annotations

import frappe

from central.iam import (
	can,
	get_user_team_names,
	get_user_team_names_with_capability,
	is_active_team_member,
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


def server_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Virtual Machine", "server:view", user)


def server_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def team_ssh_key_query_conditions(user: str | None = None) -> str:
	"""1. Operators see all keys.
	2. Users see keys in teams where they can view servers.
	3. Other users see no keys.
	"""
	return _team_field_query_conditions("Team SSH Key", "server:view", user)


def team_ssh_key_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. Operators may manage keys.
	2. Server viewers may read their team's keys.
	3. Key managers may create, change, or remove their team's keys.
	"""
	return _team_field_has_permission(doc, ("server:view",), ("server:ssh-key",), user, ptype)


def resource_action_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Resource Action", "server:view", user)


def resource_action_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. Operators can manage action records.
	2. Customers can read actions only with server view access.
	3. Customers cannot create or change action records directly.
	"""
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def site_query_conditions(user: str | None = None) -> str:
	return _team_field_query_conditions("Site", "server:view", user)


def site_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def site_domain_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every route.
	2. A user sees the routes of each team where the user holds server:view.
	3. A user without such a team sees no route."""
	return _team_field_query_conditions("Site Domain", "server:view", user)


def site_domain_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. A System Manager has every permission.
	2. A route without a team is denied.
	3. Read needs server:view on the route's team.
	4. Create, write, and delete are denied, because a route changes the regional proxy."""
	return _team_field_has_permission(doc, ("server:view",), (), user, ptype)


def vm_snapshot_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every snapshot.
	2. A user sees the snapshots of each team where the user holds server:view.
	3. A user without such a team sees no snapshot."""
	return _team_field_query_conditions("VM Snapshot", "server:view", user)


def vm_snapshot_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. A System Manager has every permission.
	2. A snapshot without a team is denied.
	3. Read needs server:view on the snapshot's team.
	4. Create, write, and delete are denied. Customers change snapshots through the API,
	   which checks server:snapshot."""
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


def user_notification_preference_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every preference.
	2. A user sees only preferences owned by that user.
	"""
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return ""
	return f"`tabUser Notification Preference`.`user` = {frappe.db.escape(user)}"


def user_notification_preference_has_permission(
	doc, user: str | None = None, ptype: str | None = None, **kwargs
) -> bool:
	"""1. A System Manager has every permission.
	2. A user can act only on that user's row.
	3. The user must be an active member of the row's team.
	"""
	user = user or frappe.session.user
	if user_has_operator_bypass(user):
		return True
	return doc.user == user and bool(doc.team) and is_active_team_member(user, doc.team)


def pilot_credential_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every credential.
	2. All other users see no credential because it contains authentication state.
	"""
	return _operator_only_query_conditions(user)


def pilot_credential_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. A System Manager has every permission.
	2. All other users have no direct permission because Pilot uses token authentication.
	"""
	return user_has_operator_bypass(user or frappe.session.user)


def team_notification_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every stored notification.
	2. Customers use the capability-filtered notification feed and cannot query records directly.
	"""
	return _operator_only_query_conditions(user)


def team_notification_has_permission(
	doc, user: str | None = None, ptype: str | None = None, **kwargs
) -> bool:
	"""1. A System Manager has every permission.
	2. Customers have no direct document permission because the feed applies recipient policy.
	"""
	return user_has_operator_bypass(user or frappe.session.user)


def team_service_query_conditions(user: str | None = None) -> str:
	"""1. A System Manager sees every service record.
	2. Customers use the service API, which redacts credentials and applies service capabilities.
	"""
	return _operator_only_query_conditions(user)


def team_service_has_permission(doc, user: str | None = None, ptype: str | None = None, **kwargs) -> bool:
	"""1. A System Manager has every permission.
	2. Customers have no direct permission because the record contains service credentials.
	"""
	return user_has_operator_bypass(user or frappe.session.user)


def _operator_only_query_conditions(user: str | None = None) -> str:
	return "" if user_has_operator_bypass(user or frappe.session.user) else "1 = 0"


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
