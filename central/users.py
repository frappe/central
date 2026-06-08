from __future__ import annotations

import frappe

from central.iam import get_user_team_names


CENTRAL_USER_ROLE = "Central User"
DEFAULT_TEAM_ROLE = "Owner"


def bootstrap_user_team(doc, method: str | None = None) -> None:
	"""Give a newly-created Central user a first Team through the normal IAM path."""
	if _should_skip_bootstrap(doc):
		return

	_ensure_central_user_role(doc.name)

	if get_user_team_names(doc.name):
		return

	if not frappe.db.exists("Team Role", DEFAULT_TEAM_ROLE):
		frappe.throw("Cannot bootstrap user team because the Owner Team Role fixture is missing.")

	team = frappe.get_doc(
		{
			"doctype": "Team",
			"team_name": _default_team_name(doc),
			"owner_user": doc.name,
			"members": [
				{
					"user": doc.name,
					"role": DEFAULT_TEAM_ROLE,
					"status": "Active",
				}
			],
		}
	)
	team.insert(ignore_permissions=True)


def _should_skip_bootstrap(doc) -> bool:
	if not doc.enabled:
		return True
	if getattr(frappe.flags, "in_install", False) or getattr(frappe.flags, "in_migrate", False):
		return True
	if not frappe.db.exists("Role", CENTRAL_USER_ROLE):
		return True
	return False


def _ensure_central_user_role(user: str) -> None:
	user_doc = frappe.get_doc("User", user)
	if CENTRAL_USER_ROLE in {row.role for row in user_doc.roles}:
		return

	user_doc.append_roles(CENTRAL_USER_ROLE)
	user_doc.save(ignore_permissions=True)


def _default_team_name(doc) -> str:
	label = doc.full_name or doc.first_name or doc.email or doc.name
	return f"{label}'s Team"
