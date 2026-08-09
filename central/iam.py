from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils.caching import request_cache

OPERATOR_BYPASS_ROLE = "System Manager"

# Bumped whenever the capability taxonomy changes. Stamped into the SSO assertion
# (`cap_version`) so a bench can detect drift from its own `BENCH_CAPS` mirror.
# v3: server is the atomic unit — the bench plane (site:* + server:config) and the
# redundant asset:view are dropped; role capabilities live at team + server level
# only. The plane field and the bench-caps SSO mint stay, so site caps can return
# under the bench plane later with no contract change.
CAPABILITY_VERSION = 4

# Capability implications: granting the key implies every cap in the value. Acting
# on a resource is meaningless without seeing it, so we close every grant under
# these before it is asserted or evaluated — the role builder can let a user tick
# `server:create` without also remembering `server:view`/`cluster:view`, and a grant
# hand-crafted through the API can't bypass it either. Phase 1: scope is still "*".
CAP_IMPLICATIONS = {
	"server:open": ("server:view",),
	"server:create": ("server:view", "cluster:view"),
	"server:terminate": ("server:view",),
	"server:power": ("server:view",),
	"server:resize": ("server:view",),
	"server:snapshot": ("server:view",),
	"service:manage": ("service:view",),
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
	# Resolve before the cached call: the request cache must key on the concrete
	# user, never on a bare no-arg () that would pin the first caller's session
	# user (e.g. Administrator) onto every later caller in the same request.
	return _user_has_operator_bypass(user or frappe.session.user)


@request_cache
def _user_has_operator_bypass(user: str) -> bool:
	return OPERATOR_BYPASS_ROLE in frappe.get_roles(user)


def get_all_capabilities() -> list[str]:
	return frappe.get_all("Capability", pluck="name", order_by="name")


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


def is_active_team_member(user: str, team: str) -> bool:
	"""
	Whether `user` is an active member of the active team `team`. A scoped
	existence check — cheaper than resolving grants or listing every team.
	"""

	member = frappe.qb.DocType("Team Member")
	team_doc = frappe.qb.DocType("Team")

	query = (
		frappe.qb.from_(member)
		.join(team_doc)
		.on(team_doc.name == member.parent)
		.select(member.name)
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.user == user)
			& (member.status == "Active")
			& (team_doc.name == team)
			& (team_doc.status == "Active")
		)
		.limit(1)
	)

	return bool(query.run())


def resolve_team(user: str, team: str | None = None) -> str:
	"""The team to act on: the one given, else the user's sole active team. With
	zero or many teams and none specified, the caller must pick one."""
	if team:
		return team
	teams = get_user_team_names(user)
	if len(teams) != 1:
		frappe.throw(_("Specify a team."), frappe.ValidationError)
	return teams[0]


def get_user_team_names_with_capability(user: str, capability: str) -> list[str]:
	"""Teams where the user holds `capability` on any resource — a team-level question
	(does the cap appear at all), the same shape as `can()` with no resource named."""
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
			member.resource_type,
			member.resource_name,
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


@request_cache
def resolve_user_grants(user: str) -> dict[str, list[dict[str, Any]]]:
	"""Resolve Team Member -> Team Role -> Capability into token-ready grants.

	Request-cached: `can()` (via permission_query_conditions on every Asset/Site/
	Team Invitation list query) and the notification feed call this per row/member,
	so within one request the 4-table join runs once per user, not per call."""
	grants_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)

	if user_has_operator_bypass(user):
		caps = get_all_capabilities()
		for team in frappe.get_all("Team", filters={"status": "Active"}, pluck="name", order_by="name"):
			grants_by_team[team].append(
				{
					"role": OPERATOR_BYPASS_ROLE,
					"source": "operator",
					"resource_type": "*",
					"resource_name": None,
					"scope": "*",
					"caps": caps,
				}
			)
		return dict(grants_by_team)

	grants_by_key = {}
	for row in _get_membership_capability_rows(user):
		if not row.is_system and row.role_team != row.team:
			continue

		# A member can hold the same role scoped to several resources, so the grant
		# key includes the resource scope — each (role, resource) pair is its own grant.
		resource_type = row.resource_type or "*"
		resource_name = row.resource_name if resource_type != "*" else None
		key = (row.team, row.role, resource_type, resource_name)
		if key not in grants_by_key:
			grants_by_key[key] = {
				"role": row.role,
				"source": "member",
				"resource_type": resource_type,
				"resource_name": resource_name,
				"scope": "*" if resource_type == "*" else f"{resource_type}:{resource_name}",
				"caps": [],
			}
			grants_by_team[row.team].append(grants_by_key[key])

		if row.capability not in grants_by_key[key]["caps"]:
			grants_by_key[key]["caps"].append(row.capability)

	# Close every grant under the implication rules so enforcement (`can`, the SSO
	# mint, the capability reads) always sees a self-consistent set — never
	# server:create without the server:view/cluster:view it depends on.
	for grant in grants_by_key.values():
		grant["caps"] = expand_capabilities(grant["caps"])

	return dict(grants_by_team)


def clear_grants_cache() -> None:
	"""Drop the request-cached IAM grants after a Team write, so later capability checks
	in the same request see the new membership. This also isolates test methods, which
	share one request while each rebuilds its team under a fresh name. Clearing the whole
	request cache is safe — it is transparent, and Team writes are rare."""
	cache = getattr(frappe.local, "request_cache", None)
	if cache is not None:
		cache.clear()


def get_fc_teams_claim(user: str | None = None) -> dict[str, list[dict[str, Any]]]:
	"""The `fc_teams` OIDC claim benches mirror. The bench contract is not yet
	scope-aware (spec/ATLAS_COORDINATION.md), so collapse each team's grants to one
	entry per role with scope `"*"` and the union of caps — identical to what an
	un-updated bench already expects. Emitting the real per-grant scope (and bumping
	CAPABILITY_VERSION) is a coordinated follow-up with the bench reader."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return {}

	claim: dict[str, list[dict[str, Any]]] = {}
	for team, team_grants in resolve_user_grants(user).items():
		by_role: dict[str, dict[str, Any]] = {}
		for grant in team_grants:
			entry = by_role.setdefault(
				grant["role"],
				{"role": grant["role"], "source": grant["source"], "scope": "*", "caps": []},
			)
			for cap in grant["caps"]:
				if cap not in entry["caps"]:
					entry["caps"].append(cap)
		claim[team] = list(by_role.values())
	return claim


def can(
	user: str,
	team: str,
	capability: str,
	resource_type: str | None = None,
	resource_name: str | None = None,
) -> bool:
	# No pre-flight db.exists probes: resolve_user_grants only returns Active teams
	# (the join filters team.status), so an inactive/unknown team yields no grants,
	# and an unknown capability simply won't match any grant's caps — both fall
	# through to False without a separate round-trip. resolve_user_grants is
	# request-cached, so the per-row/per-member callers pay one join, not N.
	#
	# `resource_name` is None → "does the user hold this cap on any resource" (the
	# team-level / list-gate question, unchanged from before scoped grants). Naming a
	# resource narrows it: only an all-resources (`*`) grant or a grant scoped to
	# exactly that (resource_type, resource_name) qualifies.
	if user_has_operator_bypass(user):
		return True

	for grant in resolve_user_grants(user).get(team, []):
		if capability not in grant.get("caps", []):
			continue
		if resource_name is None:
			return True
		gtype = grant.get("resource_type", "*")
		if gtype == "*" or (gtype == resource_type and grant.get("resource_name") == resource_name):
			return True

	return False


def resolve_resource_scope(user: str, capability: str, resource_type: str) -> dict[str, Any]:
	"""For a resource-level `capability` on a `resource_type` (`"Server"`/`"Site"`),
	map each team the user may act in to either `"*"` (all resources of that type in
	the team) or the set of resource names an explicit scoped grant allows. Teams with
	no covering grant are omitted. Drives the Asset/Site list `permission_query_conditions`."""
	scope: dict[str, Any] = {}
	for team, team_grants in resolve_user_grants(user).items():
		allowed: set[str] = set()
		wildcard = False
		for grant in team_grants:
			if capability not in grant.get("caps", []):
				continue
			gtype = grant.get("resource_type", "*")
			if gtype == "*":
				wildcard = True
				break
			if gtype == resource_type and grant.get("resource_name"):
				allowed.add(grant["resource_name"])
		if wildcard:
			scope[team] = "*"
		elif allowed:
			scope[team] = allowed
	return scope


def get_effective_permissions(user: str, team: str | None = None) -> dict[str, Any]:
	grants = resolve_user_grants(user)
	if team:
		grants = {team: grants.get(team, [])}

	effective = {}
	for team_name, team_grants in grants.items():
		caps = sorted({cap for grant in team_grants for cap in grant.get("caps", [])})
		effective[team_name] = {"caps": caps, "grants": team_grants}

	return {"user": user, "teams": effective}
