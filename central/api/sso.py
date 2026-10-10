import frappe
from frappe import _


@frappe.whitelist(methods=["GET"])
def get_bench_link(server: str, team: str | None = None) -> dict:
	"""A one-click link into the bench of `server` (a VM resource_id), as ``{gateway}/?sid=<jwt>``."""
	doc = frappe.get_doc("Virtual Machine", server)
	if team and team != doc.team:
		frappe.throw(_("That server isn't in this team."), frappe.PermissionError)

	return {"url": doc.get_bench_login_url(frappe.session.user)}
