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
# redundant server:view are dropped; role capabilities live at team + server level
# only. The plane field and the bench-caps SSO mint stay, so site caps can return
# under the bench plane later with no contract change.
CAPABILITY_VERSION = 5

# Capability implications: granting the key implies every cap in the value. Acting
# on a resource is meaningless without seeing it, so we close every grant under
# these before it is asserted or evaluated — the role builder can let a user tick
# `server:create` without also remembering `server:view`/`cluster:view`, and a grant
# hand-crafted through the API can't bypass it either.
CAP_IMPLICATIONS = {
	"server:create": ("server:view", "cluster:view"),
	"server:terminate": ("server:view",),
	"server:power": ("server:view",),
	"server:resize": ("server:view",),
	"server:snapshot": ("server:view",),
	"server:ssh-key": ("server:view",),
	"service:manage": ("service:view",),
}

# The capabilities a grant can scope to one server. Every other capability is team-wide,
# so a grant scoped to a server or site never answers for it.
SERVER_CAPABILITIES = frozenset(
	{"server:view", "server:power", "server:resize", "server:snapshot", "server:terminate"}
)
# The scope of a team-wide grant. A scoped grant's scope is its server's name.
ALL_SERVERS = "*"


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
		.distinct()
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
	"""Teams where the user holds `capability` team-wide or on at least one server."""
	return sorted(get_allowed_servers(user, capability))


def _get_membership_capability_rows(user: str) -> list[dict[str, Any]]:
	team = frappe.qb.DocType("Team")
	member = frappe.qb.DocType("Team Member")
	team_role = frappe.qb.DocType("Team Role")
	role_capability = frappe.qb.DocType("Role Capability")
	site = frappe.qb.DocType("Site")
	server = frappe.qb.DocType("Virtual Machine")

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
		# A scoped grant counts only while its resource belongs to the team. A site is one
		# machine, so a grant on a site is a grant on its server.
		.left_join(server)
		.on(
			(member.resource_type == "Server")
			& (server.name == member.resource_name)
			& (server.team == team.name)
		)
		.left_join(site)
		.on((member.resource_type == "Site") & (site.name == member.resource_name) & (site.team == team.name))
		.select(
			team.name.as_("team"),
			member.role,
			member.resource_type,
			server.name.as_("server"),
			site.server.as_("site_server"),
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

	Request-cached: `can()` (via permission_query_conditions on every Virtual Machine/Site/
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
					"scope": ALL_SERVERS,
					"caps": caps,
				}
			)
		return dict(grants_by_team)

	grants_by_key = {}
	for row in _get_membership_capability_rows(user):
		if not row.is_system and row.role_team != row.team:
			continue

		scope = _get_grant_scope(row)
		if scope is None:
			continue

		key = (row.team, row.role, scope)
		if key not in grants_by_key:
			grants_by_key[key] = {"role": row.role, "source": "member", "scope": scope, "caps": []}
			grants_by_team[row.team].append(grants_by_key[key])

		if row.capability not in grants_by_key[key]["caps"]:
			grants_by_key[key]["caps"].append(row.capability)

	# Close every grant under the implication rules so enforcement (`can`, the SSO
	# mint, the capability reads) always sees a self-consistent set — never
	# server:create without the server:view/cluster:view it depends on. A scoped
	# grant then keeps only the capabilities one server can carry.
	for grant in grants_by_key.values():
		caps = expand_capabilities(grant["caps"])
		if grant["scope"] != ALL_SERVERS:
			caps = [cap for cap in caps if cap in SERVER_CAPABILITIES]
		grant["caps"] = caps

	return dict(grants_by_team)


def _get_grant_scope(row) -> str | None:
	"""ALL_SERVERS for a team-wide row, the server a scoped row grants on, or None when
	a scoped row names nothing this team owns, so the row grants nothing."""
	if not row.resource_type or row.resource_type == "*":
		return ALL_SERVERS
	if row.resource_type == "Server":
		return row.server or None
	if row.resource_type == "Site":
		return row.site_server or None
	return None


def clear_grants_cache() -> None:
	"""Drop the request-cached IAM grants after a Team write, so later capability checks
	in the same request see the new membership. This also isolates test methods, which
	share one request while each rebuilds its team under a fresh name. Clearing the whole
	request cache is safe — it is transparent, and Team writes are rare."""
	cache = getattr(frappe.local, "request_cache", None)
	if cache is not None:
		cache.clear()


def can(user: str, team: str, capability: str, server: str | None = None) -> bool:
	"""Whether `user` holds `capability` in `team`.

	1. An operator always does.
	2. With no `server`, only a team-wide grant counts: this is the team-level question.
	3. With a `server`, a team-wide grant or a grant scoped to that server counts."""
	# No pre-flight db.exists probes: resolve_user_grants only returns Active teams
	# (the join filters team.status), so an inactive/unknown team yields no grants,
	# and an unknown capability simply won't match any grant's caps — both fall
	# through to False without a separate round-trip. resolve_user_grants is
	# request-cached, so the per-row/per-member callers pay one join, not N.
	if user_has_operator_bypass(user):
		return True

	for grant in resolve_user_grants(user).get(team, []):
		if capability in grant["caps"] and grant["scope"] in (ALL_SERVERS, server):
			return True

	return False


def can_on_any_server(user: str, team: str, capability: str) -> bool:
	"""Whether `user` holds `capability` team-wide or on at least one server of `team`.
	It gates a list, which the permission rules then narrow to the allowed servers. For a
	capability that cannot be scoped, it is the same as `can` without a server."""
	return user_has_operator_bypass(user) or team in get_allowed_servers(user, capability)


def get_allowed_servers(user: str, capability: str) -> dict[str, str | frozenset[str]]:
	"""For each team where `user` holds `capability`: ALL_SERVERS for a team-wide grant,
	else the servers that scoped grants name. Teams without the capability are left out."""
	allowed: dict[str, str | frozenset[str]] = {}
	for team, team_grants in resolve_user_grants(user).items():
		scopes = {grant["scope"] for grant in team_grants if capability in grant["caps"]}
		if ALL_SERVERS in scopes:
			allowed[team] = ALL_SERVERS
		elif scopes:
			allowed[team] = frozenset(scopes)
	return allowed


def get_server_capabilities(user: str, team: str, server: str) -> list[str]:
	"""The capabilities `user` holds on one server, for the console's buttons."""
	return sorted(cap for cap in SERVER_CAPABILITIES if can(user, team, cap, server=server))


def get_effective_permissions(user: str, team: str | None = None) -> dict[str, Any]:
	grants = resolve_user_grants(user)
	if team:
		grants = {team: grants.get(team, [])}

	effective = {}
	for team_name, team_grants in grants.items():
		caps = sorted({cap for grant in team_grants for cap in grant.get("caps", [])})
		effective[team_name] = {"caps": caps, "grants": team_grants}

	return {"user": user, "teams": effective}
