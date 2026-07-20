from __future__ import annotations

import frappe
from frappe import _

from central.iam import can


def assert_site_owner(site: str, team: str) -> None:
	"""A site must belong to the team consuming the service."""
	owner = frappe.db.get_value("Site", site, "team")
	if not owner:
		frappe.throw(_("Unknown site {0}.").format(site))

	if owner != team:
		frappe.throw(_("Site {0} does not belong to this team.").format(site), frappe.PermissionError)


def assert_capability(team: str, capability: str) -> None:
	"""Gate a team-scoped service action on an IAM capability (service:view reads,
	service:manage mutations). Operators bypass via System Manager."""
	if not can(frappe.session.user, team, capability):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def assert_operator() -> None:
	"""Platform-operator gate for backend registration (System Manager only)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
