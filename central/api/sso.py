import frappe
from frappe import _

from central.iam import can
from central.sso import mint_bench_login

# Open-in-bench: hand the signed-in user a one-click link into their bench. Central mints a
# short-lived admin SID signed with its Pilot key; the bench verifies it offline against the
# JWKS (no Atlas round-trip, no per-bench secret). The SID rides `{gateway}/?sid=`, which the
# bench SPA consumes and exchanges at POST /api/login. `aud` is the bench's audience id (its
# pilot_credential_id), so a SID minted for one bench is rejected by any other. The SID is
# single-use (jti + short TTL), so each Open mints a fresh one.


@frappe.whitelist(methods=["GET"])
def get_bench_link(server: str, team: str | None = None) -> dict:
	"""Return the URL to open a bench at, as ``{gateway}/sso?sid=<jwt>``.

	Pass `server` (a VM resource_id) to open that server: `server:console` on that server is the
	gate, and the VM must be Running with a bench gateway in an active region."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in first."), frappe.PermissionError)
	return _server_login_link(server, team, user)


def _server_login_link(server: str, team: str | None, user: str) -> dict:
	"""A one-click login URL for a Running VM in an active region, gated on `server:console`."""
	doc = frappe.get_doc("Virtual Machine", server)
	if team and team != doc.team:
		frappe.throw(_("That server isn't in this team."), frappe.PermissionError)
	if not can(user, doc.team, "server:console", server=doc.name):
		frappe.throw(_("You can't open servers for this team."), frappe.PermissionError)

	if doc.status != "Running":
		frappe.throw(_("Server is {0}, not running.").format(doc.status.lower()), frappe.ValidationError)
	if frappe.db.get_value("Region", doc.region, "status") != "Active":
		frappe.throw(_("That region is not active."), frappe.ValidationError)

	gateway = (doc.gateway_url or "").rstrip("/")
	if not gateway:
		frappe.throw(_("This server has no bench gateway yet."), frappe.ValidationError)

	# The bench verifies the SID against its own audience id, which its Pilot Credential holds.
	audience = frappe.db.get_value(
		"Pilot Credential", {"server": doc.resource_id, "status": "Active"}, "audience_id"
	)
	if not audience:
		frappe.throw(_("This server's pilot hasn't enrolled yet."), frappe.ValidationError)

	return {"url": f"{gateway}/?sid={mint_bench_login(audience)}"}
