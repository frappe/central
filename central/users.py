from __future__ import annotations

import frappe
from frappe.utils import today

CENTRAL_USER_ROLE = "Central User"


def grant_central_user_role(doc, method: str | None = None) -> None:
	"""Give a newly created user the Central User role.

	A new user gets no team here. An invited user joins the invited team when the
	signup accepts the invitation. Anyone else creates a team in console onboarding."""
	if _should_skip_role_grant(doc):
		return

	if CENTRAL_USER_ROLE not in {row.role for row in doc.roles}:
		doc.add_roles(CENTRAL_USER_ROLE)


def get_pending_invitations(user: str) -> list[str]:
	return frappe.get_all(
		"Team Invitation",
		filters={"email": user, "status": "Pending", "expires_on": [">=", today()]},
		pluck="name",
		order_by="creation asc",
	)


def _should_skip_role_grant(doc) -> bool:
	if not doc.enabled:
		return True
	if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
		return True
	if not frappe.db.exists("Role", CENTRAL_USER_ROLE):
		return True
	return False
