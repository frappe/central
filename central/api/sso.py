from urllib.parse import urlencode

import frappe
from frappe import _


@frappe.whitelist(methods=["GET"])
def get_bench_link(server: str, team: str | None = None) -> dict:
	"""A one-click link into the bench of `server` (a VM resource_id), as ``{gateway}/?sid=<jwt>``."""
	doc = frappe.get_doc("Virtual Machine", server)
	if team and team != doc.team:
		frappe.throw(_("That server isn't in this team."), frappe.PermissionError)

	return {"url": doc.get_bench_login_url(frappe.session.user)}


# nosemgrep: guest-whitelisted-method -- a guest only gets the dashboard link, which signs them in first.
@frappe.whitelist(allow_guest=True, methods=["GET"])
def open_bench(pilot: str) -> None:
	"""Send the browser straight into the bench whose Pilot audience is `pilot`.

	A guest, or a refusal, goes to the dashboard's own link for the bench, which signs in or says why."""
	frappe.local.response.type = "redirect"
	frappe.local.response.location = (
		f"/dashboard/servers?{urlencode({'pilot': pilot, 'action': 'open-bench'})}"
	)
	if frappe.session.user == "Guest":
		return

	server = frappe.db.get_value("Pilot Credential", {"audience_id": pilot, "status": "Active"}, "server")
	if not server:
		return

	try:
		url = frappe.get_doc("Virtual Machine", server).get_bench_login_url(frappe.session.user)
	except (frappe.PermissionError, frappe.ValidationError):
		frappe.clear_messages()
		return

	frappe.local.response.location = url
