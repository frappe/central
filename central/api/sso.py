from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, resolve_team
from central.sso import bench_gateway, mint_bench_login

# Open-in-bench: hand the signed-in user a one-click link into their bench. Central mints a
# short-lived admin SID signed with its RSA key; the bench verifies it offline against the
# JWKS (no Atlas round-trip, no per-bench secret). The SID rides `{gateway}/?sid=`, which the
# bench SPA consumes and exchanges at POST /api/login. `aud` is the bench's audience id (its
# pilot_credential_id), so a SID minted for one bench is rejected by any other. The SID is
# single-use (jti + short TTL), so each Open mints a fresh one.

DEV_AUDIENCE = "local-bench"  # audience for the explicit-gateway dev shortcut (no Asset)


@frappe.whitelist(methods=["GET"])
def get_bench_link(asset: str | None = None, team: str | None = None, gateway_url: str | None = None) -> dict:
	"""Return the URL to open a bench at, as ``{gateway}/sso?sid=<jwt>``.

	Pass `asset` (a VM resource_id) to open that server: `server:open` on its team is the
	gate (distinct from `server:view`, which only lists it), and the VM must be Running with
	a bench gateway on an Active cluster. `gateway_url` (no asset) is the dev shortcut: open
	an explicit gateway, minting against a fixed dev audience."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sign in first."), frappe.PermissionError)
	if asset:
		return _asset_login_link(asset, team, user)
	team = resolve_team(user, team)
	if not can(user, team, "server:open"):
		frappe.throw(_("You can't open servers for this team."), frappe.PermissionError)
	target = gateway_url.rstrip("/") if gateway_url else bench_gateway()
	return {"url": f"{target}/?sid={mint_bench_login(DEV_AUDIENCE)}"}


def _asset_login_link(asset: str, team: str | None, user: str) -> dict:
	"""Resolve a VM Asset to its one-click login URL, gated on `server:open`.

	get_doc enforces the team-scoped Asset read perm, so a user who can't see the VM can't
	probe it here either. The VM must be Running and live on an Active cluster, with a bench
	gateway. The SID is Central-signed, scoped to the VM's resource_id, and freshly minted on
	every Open (it is single-use)."""
	doc = frappe.get_doc("Asset", asset)
	if team and team != doc.team:
		frappe.throw(_("That server isn't in this team."), frappe.PermissionError)
	# Scope-aware: doc.name is the Asset name (= resource_id), so a grant scoped to
	# another server can't open this one even if get_doc's read perm let it be seen.
	if not can(user, doc.team, "server:open", "Server", doc.name):
		frappe.throw(_("You can't open this server."), frappe.PermissionError)
	if doc.status != "Running":
		frappe.throw(_("Server is {0}, not running.").format(doc.status.lower()), frappe.ValidationError)
	if frappe.db.get_value("Atlas Instance", doc.cluster, "status") != "Active":
		frappe.throw(_("That cluster is not active."), frappe.ValidationError)
	gateway = (doc.gateway_url or "").rstrip("/")
	if not gateway:
		frappe.throw(_("This server has no bench gateway yet."), frappe.ValidationError)
	# The SID's audience is the bench's audience id (its pilot_credential_id), not the VM
	# resource_id — that is what the bench verifies against. Resolve it from the pilot
	# credential bound to this VM; a VM whose pilot hasn't enrolled yet can't be opened.
	audience = frappe.db.get_value(
		"Pilot Credential", {"asset": doc.resource_id, "status": "Active"}, "audience_id"
	)
	if not audience:
		frappe.throw(_("This server's pilot hasn't enrolled yet."), frappe.ValidationError)
	return {"url": f"{gateway}/?sid={mint_bench_login(audience)}"}
