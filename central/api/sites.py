from __future__ import annotations

import frappe
from frappe import _

from central.api.site_login import site_login_url
from central.iam import can


@frappe.whitelist(methods=["GET"])
def get_site(name: str) -> dict:
	"""Return the authorized Site mirror and request login from its own Pilot when running."""
	user = frappe.session.user
	mirror = frappe.db.get_value("Site", name, ["team", "cluster", "status"], as_dict=True)
	if not mirror:
		frappe.throw(_("No site '{0}'.").format(name), frappe.DoesNotExistError)
	if not can(user, mirror.team, "server:view"):
		frappe.throw(_("You can't view this site."), frappe.PermissionError)

	doc = frappe.get_doc("Site", name)
	doc.check_permission("read")
	running = doc.status == "Running"
	return {
		"name": doc.name,
		"status": doc.status,
		"url": doc.url if running else None,
		"login_url": site_login_url(doc) if running else None,
	}
