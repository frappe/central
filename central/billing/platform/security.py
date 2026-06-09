# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Authorisation primitives (issue #22).

Two billing roles and the guards every customer/admin endpoint funnels through,
so a cluster-scoped Agent API key (which holds neither role) can never reach a
customer or admin billing endpoint — it gets a 403. `require_team_access` is the
customer-scoping the dashboards (#18) build on: a Billing User only ever sees
their own team.
"""

import frappe

BILLING_ADMIN = "Billing Admin"
BILLING_USER = "Billing User"


def ensure_billing_roles():
	"""Create the billing roles if absent (run from after_migrate)."""
	for role in (BILLING_ADMIN, BILLING_USER):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def is_billing_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = frappe.get_roles(user)
	return BILLING_ADMIN in roles or "System Manager" in roles


def require_billing_admin():
	"""Gate an admin endpoint. Anything without the role (incl. the Agent key)
	gets a PermissionError, which Frappe renders as HTTP 403."""
	if not is_billing_admin():
		frappe.throw("Billing Admin role is required for this endpoint.", frappe.PermissionError)


def get_user_team(user: str | None = None):
	"""The team a Billing User is scoped to. In the real Central this derives
	from team membership; modelled here as a User field, overridable in tests."""
	user = user or frappe.session.user
	if frappe.get_meta("User").has_field("billing_team"):
		return frappe.db.get_value("User", user, "billing_team")
	return None


def require_team_access(team: str):
	"""A customer endpoint: admins see any team, a Billing User only their own.
	Passing another team's name is rejected (never silently widened)."""
	if is_billing_admin():
		return
	if get_user_team() != team:
		frappe.throw("Not permitted to access this team's billing.", frappe.PermissionError)
