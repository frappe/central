from __future__ import annotations

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

	Pass `server` (a VM resource_id) to open that server: `server:view` on that server is the
	gate, and the VM must be Running with a bench gateway in an active region."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in first."), frappe.PermissionError)
	return _server_login_link(server, team, user)


def _server_login_link(server: str, team: str | None, user: str) -> dict:
	"""Resolve a VM VirtualMachine to its one-click login URL, gated on `server:view`.

	get_doc enforces the team-scoped VirtualMachine read perm, so a user who can't see the VM can't
	probe it here either. The VM must be Running and live in an active region, with a bench
	gateway. The SID is Central-signed, scoped to the VM's resource_id, and freshly minted on
	every Open (it is single-use)."""
	doc = frappe.get_doc("Virtual Machine", server)
	if team and team != doc.team:
		frappe.throw(_("That server isn't in this team."), frappe.PermissionError)
	if not can(user, doc.team, "server:view", server=doc.name):
		frappe.throw(_("You can't open servers for this team."), frappe.PermissionError)
	if doc.status != "Running":
		frappe.throw(_("Server is {0}, not running.").format(doc.status.lower()), frappe.ValidationError)
	if frappe.db.get_value("Region", doc.region, "status") != "Active":
		frappe.throw(_("That region is not active."), frappe.ValidationError)
	gateway = (doc.gateway_url or "").rstrip("/")
	if not gateway:
		frappe.throw(_("This server has no bench gateway yet."), frappe.ValidationError)
	# The SID's audience is the bench's audience id (its pilot_credential_id), not the VM
	# resource_id — that is what the bench verifies against. Resolve it from the pilot
	# credential bound to this VM; a VM whose pilot hasn't enrolled yet can't be opened.
	audience = frappe.db.get_value(
		"Pilot Credential", {"server": doc.resource_id, "status": "Active"}, "audience_id"
	)
	if not audience:
		frappe.throw(_("This server's pilot hasn't enrolled yet."), frappe.ValidationError)
	return {"url": f"{gateway}/?sid={mint_bench_login(audience)}"}
