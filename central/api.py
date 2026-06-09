from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, get_effective_permissions, get_fc_teams_claim


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
