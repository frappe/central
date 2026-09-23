# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Merge the redundant server:open capability into server:view."""

import frappe

OLD_CAPABILITY = "server:open"
NEW_CAPABILITY = "server:view"


def execute() -> None:
	_update_role_capabilities()
	_update_permission_probes()
	frappe.db.delete("Capability", {"name": OLD_CAPABILITY})


def _update_role_capabilities() -> None:
	rows = frappe.get_all(
		"Role Capability",
		filters={"capability": OLD_CAPABILITY},
		fields=["name", "parent"],
	)
	for row in rows:
		if frappe.db.exists(
			"Role Capability",
			{"parenttype": "Team Role", "parent": row.parent, "capability": NEW_CAPABILITY},
		):
			frappe.db.delete("Role Capability", {"name": row.name})
		else:
			frappe.db.set_value(
				"Role Capability", row.name, "capability", NEW_CAPABILITY, update_modified=False
			)


def _update_permission_probes() -> None:
	if not frappe.db.has_table("IAM Permission Probe"):
		return

	for name in frappe.get_all("IAM Permission Probe", filters={"capability": OLD_CAPABILITY}, pluck="name"):
		frappe.db.set_value(
			"IAM Permission Probe",
			name,
			"capability",
			NEW_CAPABILITY,
			update_modified=False,
		)
