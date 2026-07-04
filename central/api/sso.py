from __future__ import annotations

import frappe

from central.iam import can, resolve_team
from central.integrations.atlas import AtlasClient
from central.sso import _bench_sso_url, mint_bench_assertion

# Open-in-bench: hand the signed-in user a one-click link into their bench VM. For a
# real VM (asset) that link is a login URL Atlas mints in the guest — a scoped,
# single-use admin SID (a 5-minute JWT). Because it's single-use, we re-mint on every
# Open rather than reuse a stored URL, so the click always carries a live, unused SID.
# The legacy SSO-assertion path (central.sso) survives only for the gateway_url dev
# shortcut, until RS256 signing (#21) makes it prod-safe.


@frappe.whitelist(methods=["GET"])
def get_bench_link(asset: str | None = None, team: str | None = None, gateway_url: str | None = None) -> dict:
	"""Return the URL to open a bench VM at.

	Pass `asset` (a server resource_id) to open that server: `server:open` on its
	team is the gate (distinct from `server:view`, which only lists it), and the VM
	must be Running with a bench front door on an Active cluster. The URL handed back
	is Atlas's one-click login URL — a scoped admin session minted in the guest. It is
	short-lived (an admin JWT lasts minutes), so a stored URL past its expiry is
	regenerated here before it's returned, keeping the click live.

	`gateway_url` (no asset) is the dev shortcut: mint a shared-secret SSO assertion
	against an explicit gateway, used only until the registry "Open" wires `asset` in."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Sign in first.", frappe.PermissionError)
	if asset:
		return _asset_login_link(asset, team, user)
	team = resolve_team(user, team)
	if not can(user, team, "server:open"):
		frappe.throw("You can't open servers for this team.", frappe.PermissionError)
	target = (gateway_url or _bench_sso_url()).rstrip("/")
	if not target.endswith("/sso"):
		target += "/sso"
	return {"url": f"{target}?assertion={mint_bench_assertion(user, team)}"}


def _asset_login_link(asset: str, team: str | None, user: str) -> dict:
	"""Resolve a VM Asset to its usable one-click login URL, gated on `server:open`.

	get_doc enforces the team-scoped Asset read perm, so a user who can't see the VM
	can't probe it here either. The VM must be Running and live on an Active cluster.
	The login URL is always re-minted via Atlas (the admin SID is single-use, so the
	stored mirror value is worthless on Open) and the mirror is refreshed before we
	return; if the re-mint can't reach Atlas we hand back nothing and refuse below."""
	doc = frappe.get_doc("Asset", asset)
	if team and team != doc.team:
		frappe.throw("That VM isn't in this team.", frappe.PermissionError)
	if not can(user, doc.team, "server:open"):
		frappe.throw("You can't open servers for this team.", frappe.PermissionError)
	if doc.status != "Running":
		frappe.throw(f"VM is {doc.status.lower()}, not running.", frappe.ValidationError)
	if frappe.db.get_value("Atlas Instance", doc.cluster, "status") != "Active":
		frappe.throw("That cluster is not active.", frappe.ValidationError)
	url = _fresh_asset_login_url(doc)
	if not url:
		# Running + Active but the re-mint couldn't reach Atlas. Surface it rather than
		# hand back the stored (single-use, likely already-spent) SID as a dead link.
		frappe.throw("Couldn't get a login URL for this VM. Try again shortly.", frappe.ValidationError)
	return {"url": url}


def _fresh_asset_login_url(doc) -> str:
	"""The VM's usable login URL: always a freshly regenerated one.

	Unlike a site session (a reusable 24h browser session), a bench Asset's login URL
	is a **single-use** admin SID — a 5-minute JWT that `bench generate-admin-session`
	invalidates the moment it's redeemed. So the stored mirror URL is worthless on
	Open: even inside its 5-minute clock it may already be spent (the tenant clicked
	once), and a spent SID is a dead login. We re-mint on every Open so the click
	always carries a live, unused SID — the timestamp is not a usability signal here.

	Re-minting also closes the just-went-Running window where the mirror carries no
	URL at all: the guest mint lands on Atlas but the status push that carries it can
	miss (the Running flip is a db_set that doesn't fire the push), so the mirror only
	catches up on the next reconcile. Asking Atlas directly covers both cases.

	NOT best-effort: if the re-mint can't reach Atlas we return empty (the caller then
	refuses Open) rather than falling back to the stored URL. For a single-use SID the
	stored value is almost certainly already consumed, so handing it back would open a
	dead session — a clean "try again shortly" is better than a broken login."""
	try:
		fresh = AtlasClient(frappe.get_doc("Atlas Instance", doc.cluster)).regenerate_vm_login(doc.resource_id)
		from central.central.doctype.asset.asset import Asset

		Asset.mirror_vm(doc.cluster, fresh, synced_at=frappe.utils.now_datetime())
		return fresh.get("login_url") or ""
	except Exception:
		frappe.log_error(title=f"Regenerate login failed for VM {doc.resource_id}")
		return ""
