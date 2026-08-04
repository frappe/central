from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today

from central.iam import get_user_team_names

CENTRAL_USER_ROLE = "Central User"
DEFAULT_TEAM_ROLE = "Owner"


def bootstrap_user_team(doc, method: str | None = None) -> None:
	"""Provision Central access for a newly created user."""
	if _should_skip_bootstrap(doc):
		return

	_ensure_central_user_role(doc)

	if not frappe.db.exists("Team Role", DEFAULT_TEAM_ROLE):
		frappe.throw(_("Cannot bootstrap user team because the Owner Team Role fixture is missing."))

	if not get_user_team_names(doc.name):
		team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": _default_team_name(doc),
				"owner_user": doc.name,
				"is_staging_trial": 1 if frappe.conf.get("central_trial_provisioning") else 0,
				"members": [
					{
						"user": doc.name,
						"role": DEFAULT_TEAM_ROLE,
						"status": "Active",
					}
				],
			}
		)
		team.flags.from_user_bootstrap = True
		# User.after_insert runs as Guest during self-signup; this is trusted
		# provisioning of the user's own team, gated upstream by OTP verification.
		team.insert(ignore_permissions=True)

	_accept_pending_invitations(doc.name)


def _accept_pending_invitations(user: str) -> None:
	for name in frappe.get_all(
		"Team Invitation",
		filters={"email": user, "status": "Pending", "expires_on": [">=", today()]},
		pluck="name",
		order_by="creation asc",
	):
		frappe.get_doc("Team Invitation", name).accept_for_user(user)


def _should_skip_bootstrap(doc) -> bool:
	if not doc.enabled:
		return True
	if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
		return True
	if not frappe.db.exists("Role", CENTRAL_USER_ROLE):
		return True
	return False


def _ensure_central_user_role(user) -> None:
	if CENTRAL_USER_ROLE in {row.role for row in user.roles}:
		return

	user.add_roles(CENTRAL_USER_ROLE)


def _default_team_name(doc) -> str:
	label = doc.full_name or doc.first_name or doc.email or doc.name
	return f"{label}'s Team"
