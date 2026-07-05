# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing authorisation seam (issue #42, ADR 0004).

Billing defines no roles of its own. It reuses Central's capability IAM
(`central.iam`): every customer **read** funnels through `require_billing_view`
(`billing:view`), every **mutation** through `require_billing_manage`
(`billing:manage`), and the cross-team admin console through `require_operator`
(System Manager). Those capabilities ship in Central's fixtures, carried by the
system `Owner`, `Admin`, and `Billing` team roles.

A System Manager (operator) bypasses team scoping — they see/act across every
team. The cluster Agent API key holds no billing capability and is not a System
Manager, so `can(...)` is False on every customer/admin endpoint; it reaches
only the sync surface (`platform/sync.py`).
"""

from __future__ import annotations

import frappe

from central import iam

VIEW = "billing:view"
MANAGE = "billing:manage"


def is_operator(user: str | None = None) -> bool:
	"""Platform staff (System Manager) — the only cross-team bypass."""
	return iam.user_has_operator_bypass(user or frappe.session.user)


def list_billing_teams(user: str | None = None) -> list[str]:
	"""Teams the user can view billing for (their `billing:view`-capable teams)."""
	return iam.get_user_team_names_with_capability(user or frappe.session.user, VIEW)


def get_user_team(user: str | None = None) -> str | None:
	"""The caller's default billing team — the first team they can view billing for.

	Multi-team users select a current team via Central's console; here we pick a
	deterministic default so a single-team customer never has to choose.
	"""
	teams = list_billing_teams(user or frappe.session.user)
	return teams[0] if teams else None


def require_capability(team: str, capability: str) -> None:
	"""Gate on a billing capability for `team`. Operators pass unconditionally;
	everyone else must carry the capability on that team (IDOR defence — another
	team's name is never silently widened). The Agent key carries neither, so it
	gets a PermissionError, rendered as HTTP 403."""
	user = frappe.session.user
	if is_operator(user):
		return
	if not iam.can(user, team, capability):
		frappe.throw("Not permitted to access this team's billing.", frappe.PermissionError)


def require_billing_view(team: str) -> None:
	require_capability(team, VIEW)


def require_billing_manage(team: str) -> None:
	require_capability(team, MANAGE)


def require_operator() -> None:
	"""Gate the cross-team admin console — platform staff (System Manager) only."""
	if not is_operator():
		frappe.throw("Operator access is required for this endpoint.", frappe.PermissionError)
