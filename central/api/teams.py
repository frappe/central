from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.query_builder import Order

from central.iam import can, expand_capabilities, get_all_capabilities, user_has_operator_bypass
from central.utils.guards import require_capability, require_team_member

# Team-roster reads + role management for the console's Team screens. Visibility
# is "being a member" (any capability on the team); mutations delegate to the Team
# doc methods, which independently enforce team:manage_members.


@frappe.whitelist(methods=["GET"])
@require_team_member
def list_team_members(team: str) -> list[dict[str, Any]]:
	"""Roster of the team the caller belongs to (user, full name, role grants, status,
	owner flag) — one entry per user, folding their Team Member rows into a `roles` list."""
	doc = frappe.get_doc("Team", team)
	full_names = {
		u.name: u.full_name
		for u in frappe.get_all(
			"User", filters={"name": ["in", [m.user for m in doc.members]]}, fields=["name", "full_name"]
		)
	}

	roster: dict[str, dict[str, Any]] = {}
	for m in doc.members:
		entry = roster.get(m.user)
		if entry is None:
			entry = {
				"user": m.user,
				"full_name": full_names.get(m.user) or m.user,
				"roles": [],
				"status": m.status,
				"is_owner": m.user == doc.owner_user,
			}
			roster[m.user] = entry
		entry["roles"].append(
			{"role": m.role, "resource_type": m.resource_type, "resource_name": m.resource_name}
		)
	return list(roster.values())


@frappe.whitelist(methods=["GET"])
@require_team_member
def list_team_roles(team: str) -> list[dict[str, Any]]:
	"""System roles plus this team's custom roles, each with its capabilities —
	one join (Team Role ⟕ Role Capability), grouped in order (system roles first)."""
	role = frappe.qb.DocType("Team Role")
	role_capability = frappe.qb.DocType("Role Capability")

	rows = (
		frappe.qb.from_(role)
		.left_join(role_capability)
		.on(
			(role_capability.parent == role.name)
			& (role_capability.parenttype == "Team Role")
			& (role_capability.parentfield == "capabilities")
		)
		.select(role.name, role.role_name, role.is_system, role.team, role_capability.capability)
		.where((role.is_system == 1) | ((role.team == team) & (role.is_system == 0)))
		.orderby(role.is_system, order=Order.desc)
		.orderby(role.role_name)
		.orderby(role_capability.idx)
	).run(as_dict=True)

	# Fold the joined rows into one entry per role (dict keeps the system-first query order).
	roles: dict[str, dict[str, Any]] = {}
	for row in rows:
		entry = roles.get(row.name)
		if entry is None:
			entry = {
				"name": row.name,
				"role_name": row.role_name,
				"is_system": row.is_system,
				"team": row.team,
				"capabilities": [],
			}
			roles[row.name] = entry
		if row.capability:
			entry["capabilities"].append(row.capability)

	return list(roles.values())


@frappe.whitelist(methods=["GET"])
def list_capabilities() -> list[dict[str, Any]]:
	"""Every capability in the system — the palette the role builder picks from."""
	return frappe.get_all(
		"Capability",
		fields=["name", "plane", "resource", "description"],
		order_by="name asc",
	)


@frappe.whitelist(methods=["GET"])
@require_capability("team:manage_members", "You can't manage invitations for this team.")
def list_team_invitations(team: str, status: str | None = None) -> list[dict[str, Any]]:
	"""Invitations for a team — the manager's view."""
	filters: dict[str, Any] = {"team": team}
	if status:
		filters["status"] = status
	return frappe.get_all(
		"Team Invitation",
		filters=filters,
		fields=[
			"name",
			"email",
			"role",
			"resource_type",
			"resource_name",
			"status",
			"invited_by",
			"expires_on",
			"accepted_by",
			"accepted_at",
			"creation",
		],
		order_by="creation desc",
		limit=100,
	)


@frappe.whitelist(methods=["POST"])
def create_team(team_name: str) -> dict[str, Any]:
	"""Create a new team owned by the caller. The Team doc seeds the active Owner
	membership; team_has_permission gates creation to Central Users."""
	team = frappe.get_doc({"doctype": "Team", "team_name": team_name}).insert()
	return {"name": team.name, "team_name": team.team_name}


@frappe.whitelist(methods=["POST"])
@require_capability("team:edit", "You can't rename this team.")
def rename_team(team: str, team_name: str) -> dict[str, Any]:
	"""Rename a team. Team.validate re-checks team:edit on save."""
	doc = frappe.get_doc("Team", team)
	doc.team_name = team_name
	doc.save()
	return {"name": doc.name, "team_name": doc.team_name}


@frappe.whitelist(methods=["POST"])
@require_team_member
def transfer_team_ownership(team: str, user: str) -> dict[str, Any]:
	"""Hand the Owner role to another active member. Current-owner only."""
	frappe.get_doc("Team", team).transfer_ownership(user)
	return {"team": team, "owner": user}


@frappe.whitelist(methods=["POST"])
@require_capability("team:delete", "You can't delete this team.")
def delete_team(team: str) -> dict[str, Any]:
	"""Delete a team, once it owns no servers or sites (those must be torn down
	deliberately). Invitations and custom roles are cleared first so their Link
	references don't block the delete."""
	for doctype in ("Asset", "Site"):
		if frappe.db.exists(doctype, {"team": team}):
			frappe.throw(
				_("Remove this team's servers and sites before deleting it."), frappe.ValidationError
			)
	# force=True: clear the child links that would otherwise raise LinkExistsError on the Team delete.
	for name in frappe.get_all("Team Invitation", {"team": team}, pluck="name"):
		frappe.delete_doc("Team Invitation", name, ignore_permissions=True, force=True)
	for name in frappe.get_all("Team Role", {"team": team, "is_system": 0}, pluck="name"):
		frappe.delete_doc("Team Role", name, ignore_permissions=True, force=True)
	frappe.delete_doc("Team", team)
	return {"team": team, "deleted": True}


@frappe.whitelist(methods=["POST"])
def invite_team_member(
	team: str,
	email: str,
	role: str,
	expires_in_days: int = 7,
	resource_type: str = "*",
	resource_name: str | None = None,
) -> str:
	return frappe.get_doc("Team", team).invite_member(
		email,
		role,
		expires_in_days,
		resource_type=resource_type or "*",
		resource_name=resource_name,
	)


@frappe.whitelist(methods=["POST"])
def resend_invitation(invitation: str) -> dict[str, Any]:
	return frappe.get_doc("Team Invitation", invitation).resend()


@frappe.whitelist(methods=["POST"])
def revoke_invitation(invitation: str) -> dict[str, Any]:
	revoked = frappe.get_doc("Team Invitation", invitation).revoke()
	return {"invitation": invitation, "revoked": revoked}


@frappe.whitelist(methods=["POST"])
def accept_invitation(invitation: str) -> dict[str, Any]:
	return frappe.get_doc("Team Invitation", invitation).accept()


@frappe.whitelist(methods=["POST"])
def decline_invitation(invitation: str) -> dict[str, Any]:
	declined = frappe.get_doc("Team Invitation", invitation).decline()
	return {"invitation": invitation, "declined": declined}


@frappe.whitelist(methods=["POST"])
def set_team_member_roles(team: str, user: str, roles: list[dict] | str) -> dict:
	if isinstance(roles, str):
		roles = frappe.parse_json(roles)  # the console posts a JSON-encoded array
	frappe.get_doc("Team", team).set_member_roles(user, roles)
	return {"team": team, "user": user, "roles": roles}


@frappe.whitelist(methods=["POST"])
def set_team_member_status(team: str, user: str, status: str) -> dict:
	frappe.get_doc("Team", team).set_member_status(user, status)
	return {"team": team, "user": user, "status": status}


@frappe.whitelist(methods=["POST"])
def remove_team_member(team: str, user: str) -> dict:
	frappe.get_doc("Team", team).remove_member(user)
	return {"team": team, "user": user, "removed": True}


@frappe.whitelist(methods=["POST"])
@require_capability("team:manage_members", "You can't manage roles for this team.")
def create_custom_role(team: str, role_name: str, capabilities: list | str) -> dict:
	"""Create a team-scoped custom Team Role granting exactly `capabilities`."""
	if isinstance(capabilities, str):
		capabilities = frappe.parse_json(capabilities)  # the console posts a JSON-encoded array
	valid = set(get_all_capabilities())
	picked = [c for c in capabilities if c in valid]
	if not picked:
		frappe.throw(_("Pick at least one capability."), frappe.ValidationError)
	# Persist the implied dependencies too (e.g. server:create pulls in server:view +
	# cluster:view), so the saved role is usable and matches what enforcement grants.
	rows = [{"capability": c} for c in expand_capabilities(picked) if c in valid]
	# Authorized by the decorator; Team Role grants create only to System Manager, so bypass doc perms.
	role = frappe.get_doc(
		{
			"doctype": "Team Role",
			"role_name": role_name,
			"is_system": 0,
			"team": team,
			"capabilities": rows,
		}
	).insert(ignore_permissions=True)
	return {"role": role.name, "role_name": role.role_name}


@frappe.whitelist(methods=["POST"])
def delete_custom_role(role: str) -> dict:
	"""Delete a team-scoped custom role. Gated on team:manage_members for its team;
	refuses system roles and roles still referenced by a member or pending invite."""
	doc = frappe.get_doc("Team Role", role)
	if doc.is_system:
		frappe.throw(_("System roles cannot be deleted."), frappe.ValidationError)
	if not can(frappe.session.user, doc.team, "team:manage_members") and not user_has_operator_bypass():
		frappe.throw(_("You can't manage roles for this team."), frappe.PermissionError)
	if frappe.db.exists("Team Member", {"role": role}):
		frappe.throw(_("Reassign members off this role before deleting it."), frappe.ValidationError)
	if frappe.db.exists("Team Invitation", {"role": role, "status": "Pending"}):
		frappe.throw(_("A pending invitation still uses this role."), frappe.ValidationError)
	# Authorized above; the Team Role doctype grants delete only to System Manager.
	frappe.delete_doc("Team Role", role, ignore_permissions=True)
	return {"role": role, "deleted": True}
