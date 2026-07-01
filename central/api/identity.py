from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from central.iam import (
	can,
	get_all_capabilities,
	get_effective_permissions,
	get_fc_teams_claim,
	get_user_team_names,
	resolve_user_grants,
	user_has_operator_bypass,
)

# Identity and capability reads for the console, plus the observe-only endpoints
# Atlas and operators use to inspect a user's grants (spec/IAM.md).


# --- observe contract: inspect any user's grants -----------------------------
# Gated to operators or the user themselves; never mutates grants or resources.


def _assert_can_inspect(user: str) -> None:
	if frappe.session.user != user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can inspect another user's permissions"), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def fc_teams(user: str | None = None) -> dict:
	user = user or frappe.session.user
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return get_fc_teams_claim(user)


@frappe.whitelist(methods=["GET"])
def effective_permissions(user: str, team: str | None = None) -> dict:
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return get_effective_permissions(user, team)


@frappe.whitelist(methods=["GET"])
def check_capability(user: str, team: str, capability: str) -> dict:
	frappe.only_for(("System Manager", "Central User"))
	_assert_can_inspect(user)
	return {
		"user": user,
		"team": team,
		"capability": capability,
		"allowed": can(user, team, capability),
	}


# --- session reads: always the signed-in user -------------------------------


@frappe.whitelist(methods=["GET"])
def my_capabilities(team: str | None = None) -> list[str]:
	"""Capabilities the signed-in user carries on a team (or any team, if omitted).
	The console gates every screen on this: reads behind `*:view`, mutations behind
	`*:manage`. Always the session user, so it is safe for any logged-in member."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	# Operators bypass team membership everywhere in Central IAM, so the console
	# must reflect that — else its gates hide screens the API would happily serve.
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
	names = get_user_team_names(user)
	if not names:
		return []
	rows = frappe.get_all(
		"Team",
		filters={"name": ["in", names]},
		fields=["name", "team_name", "owner_user"],
		order_by="team_name asc",
	)
	return [
		{"name": r.name, "label": r.team_name or r.owner_user or r.name, "owner": r.owner_user}
		for r in rows
	]


@frappe.whitelist(methods=["GET"])
def my_invitations() -> list[dict[str, Any]]:
	"""Pending, unexpired invitations addressed to the signed-in user — the invitee's
	inbox. Each carries the inviting team's label so the console can render it without
	a second call."""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	rows = frappe.get_all(
		"Team Invitation",
		filters={"email": user, "status": "Pending", "expires_on": [">=", frappe.utils.today()]},
		fields=["name", "team", "role", "invited_by", "expires_on", "creation"],
		order_by="creation desc",
	)
	team_ids = list({row["team"] for row in rows})
	labels = (
		{t.name: t.team_name for t in frappe.get_all("Team", {"name": ["in", team_ids]}, ["name", "team_name"])}
		if team_ids
		else {}
	)
	for row in rows:
		row["team_name"] = labels.get(row["team"]) or row["team"]
	return rows


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
