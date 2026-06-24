from __future__ import annotations

import frappe

from central.iam import can, resolve_team
from central.sso import _bench_sso_url, mint_bench_assertion

# Open-in-bench: mint a short-lived SSO assertion for the signed-in user and hand
# back the bench URL to redirect to. The signing/minting lives in central.sso.


@frappe.whitelist(methods=["GET"])
def get_bench_link(asset: str | None = None, team: str | None = None, gateway_url: str | None = None) -> dict:
	"""Mint a scoped SSO assertion and return the bench URL to redirect to.

	Pass `asset` (a server resource_id) to open that server — its team and gateway
	are resolved and validated (Running, has a gateway, Active cluster). `server:open`
	on the team is the gate (distinct from `server:view`, which only lists it).
	`gateway_url` is the dev path used until the registry "Open" wires `asset` in."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Sign in first.", frappe.PermissionError)
	if asset:
		team, gateway_url = _resolve_asset_target(asset, team)
	team = resolve_team(user, team)
	if not can(user, team, "server:open"):
		frappe.throw("You can't open servers for this team.", frappe.PermissionError)
	target = (gateway_url or _bench_sso_url()).rstrip("/")
	if not target.endswith("/sso"):
		target += "/sso"
	return {"url": f"{target}?assertion={mint_bench_assertion(user, team)}"}


def _resolve_asset_target(asset: str, team: str | None) -> tuple[str, str]:
	"""Resolve a VM Asset to (team, gateway_url), refusing anything not openable.
	get_doc enforces the team-scoped Asset read perm, so a user who can't see the
	VM can't probe it here either."""
	doc = frappe.get_doc("Asset", asset)
	if team and team != doc.team:
		frappe.throw("That VM isn't in this team.", frappe.PermissionError)
	if doc.status != "Running":
		frappe.throw(f"VM is {doc.status.lower()}, not running.", frappe.ValidationError)
	if not doc.gateway_url:
		frappe.throw("VM has no gateway yet.", frappe.ValidationError)
	if frappe.db.get_value("Atlas Instance", doc.cluster, "status") != "Active":
		frappe.throw("That cluster is not active.", frappe.ValidationError)
	return doc.team, doc.gateway_url
