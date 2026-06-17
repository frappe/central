from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe

OPERATOR_BYPASS_ROLE = "System Manager"

# Bumped whenever the capability taxonomy changes. Stamped into the SSO assertion
# (`cap_version`) so a bench can detect drift from its own `BENCH_CAPS` mirror.
# v2: vm:*/bench:* collapsed into server:*; site sub-caps renamed (app:install ->
# site:apps, db:access -> site:db, log:view -> site:logs, task:run -> site:console).
CAPABILITY_VERSION = 2

# Capability implications: granting the key implies every cap in the value. Acting
# on a resource is meaningless without seeing it, so we close every grant under
# these before it is asserted or evaluated — the role builder can let a user tick
# `site:create` without also remembering `site:view`/`server:view`, and a grant
# hand-crafted through the API can't bypass it either. Phase 1: scope is still "*".
CAP_IMPLICATIONS = {
	"site:view": ("server:view",),
	"site:create": ("site:view", "server:view"),
	"site:delete": ("site:view", "server:view"),
	"site:backup": ("site:view", "server:view"),
	"site:restore": ("site:view", "server:view"),
	"site:migrate": ("site:view", "server:view"),
	"site:config": ("site:view", "server:view"),
	"site:apps": ("site:view", "server:view"),
	"site:db": ("site:view", "server:view"),
	"site:logs": ("site:view", "server:view"),
	"site:console": ("site:view", "server:view"),
	"server:open": ("server:view",),
	"server:create": ("server:view", "cluster:view"),
	"server:terminate": ("server:view",),
	"server:power": ("server:view",),
	"server:resize": ("server:view",),
	"server:snapshot": ("server:view",),
	"server:config": ("server:view",),
}


def expand_capabilities(caps: list[str]) -> list[str]:
	"""Close a capability list under CAP_IMPLICATIONS, preserving the original order
	and appending any implied caps (sorted) that weren't already granted."""
	have = set(caps)
	pending = list(caps)
	while pending:
		for implied in CAP_IMPLICATIONS.get(pending.pop(), ()):
			if implied not in have:
				have.add(implied)
				pending.append(implied)
	extra = sorted(have.difference(caps))
	return list(caps) + extra


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

	# Close every grant under the implication rules so enforcement (`can`, the SSO
	# mint, my_capabilities) always sees a self-consistent set — never site:create
	# without the site:view/server:view it depends on.
	for grant in grants_by_key.values():
		grant["caps"] = expand_capabilities(grant["caps"])

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
	# Operators (System Manager) bypass team membership everywhere in Central IAM,
	# so the console must reflect that — otherwise the UI gates hide screens the
	# API would happily serve.
	if user_has_operator_bypass(user):
		return get_all_capabilities()
	grants = resolve_user_grants(user)
	team_grants = grants.get(team, []) if team else [g for gs in grants.values() for g in gs]
	return sorted({cap for grant in team_grants for cap in grant.get("caps", [])})


@frappe.whitelist(methods=["GET"])
def my_teams() -> list[dict[str, Any]]:
	"""Teams the signed-in user can switch between in the console — the teams they
	are an active member of, each with a display label + the owner email."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	out = []
	for t in get_user_team_names(user):
		r = frappe.db.get_value("Team", t, ["team_name", "owner_user"], as_dict=True) or {}
		out.append({
			"name": t,
			"label": r.get("team_name") or r.get("owner_user") or t,
			"owner": r.get("owner_user"),
		})
	return out


@frappe.whitelist(methods=["GET"])
def search_teams(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
	"""Operator-only: any active team, for impersonation in the team switcher.
	Mirrors the IAM rule that a System Manager bypasses team membership."""
	if not user_has_operator_bypass(frappe.session.user):
		return []
	q = (query or "").strip()
	or_filters = None
	if q:
		like = f"%{q}%"
		or_filters = {"name": ["like", like], "team_name": ["like", like], "owner_user": ["like", like]}
	rows = frappe.get_all(
		"Team",
		filters={"status": "Active"},
		or_filters=or_filters,
		fields=["name", "team_name", "owner_user"],
		order_by="modified desc",
		limit=limit,
	)
	return [
		{"name": r.name, "label": r.team_name or r.owner_user or r.name, "owner": r.owner_user}
		for r in rows
	]


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
