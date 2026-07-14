from __future__ import annotations

import frappe


def execute():
	"""Central users belong in the console, not Desk.

	The "Central User" role no longer grants desk access, so every user who
	carries it is recomputed to the right `user_type`: Website User unless some
	*other* role still grants them desk access. New users get this for free via
	`central.users.bootstrap_user_team`; this patch back-fills existing ones.
	"""
	if not frappe.db.exists("Role", "Central User"):
		return

	frappe.db.set_value("Role", "Central User", "desk_access", 0)

	user_names = frappe.get_all(
		"Has Role",
		filters={"role": "Central User", "parenttype": "User"},
		pluck="parent",
	)
	for user_name in user_names:
		_recalculate_user_type(user_name)

	frappe.clear_cache()


def _recalculate_user_type(user_name: str) -> None:
	if user_name in {"Guest", "Administrator"}:
		return
	user = frappe.get_doc("User", user_name)
	user.user_type = "System User" if user.has_desk_access() else "Website User"
	user.save(ignore_permissions=True)
