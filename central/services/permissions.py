from __future__ import annotations

import frappe
from frappe import _


def assert_site_owner(site: str, team: str) -> None:
	"""A site must belong to the team consuming the service."""
	owner = frappe.db.get_value("Site", site, "team")
	if not owner:
		frappe.throw(_("Unknown site {0}.").format(site))

	if owner != team:
		frappe.throw(_("Site {0} does not belong to this team.").format(site), frappe.PermissionError)


def assert_service_manager(team: str) -> None:
	"""Phase 1 gate: System Manager only. Team capability (service:manage) is phase 2."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def assert_operator() -> None:
	"""Platform-operator gate for backend registration (System Manager only)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
