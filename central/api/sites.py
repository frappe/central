from __future__ import annotations

import frappe
from frappe import _

from central.iam import can, get_user_team_names, resolve_team
from central.integrations.atlas import AtlasClient

# Self-serve site endpoints for the SMB onboarding flow. Reads come from the Site
# mirror (kept fresh by the site.* events Atlas pushes); writes go to Atlas as the
# operator. Atlas stays policy-unaware — capability gating happens here. Every call
# resolves and authorizes a team first.
#
# Atlas exposes no tenant_sites reconcile pull, so get_site(name) is the only
# self-heal: we poll Atlas while a site is still provisioning.

_TERMINAL = {"Running", "Failed", "Terminated"}


def _default_region() -> str:
	"""The region SMB sites land in — the single Active Atlas Instance. Used only
	to route the operator call; Atlas itself defaults the site's region/domain."""
	region = frappe.db.get_value("Atlas Instance", {"status": "Active"}, "region", order_by="region asc")
	if not region:
		frappe.throw(_("No region is available — contact your operator."), frappe.ValidationError)
	return region


@frappe.whitelist(methods=["POST"])
def create_site(subdomain: str, region: str | None = None) -> dict:
	"""Provision a self-serve site for the user's team. Gated on `server:create`.

	Server is the atomic unit, so deploying a site is authorized by the same
	provisioning capability as standing up a server (site-level capabilities are
	deferred). Central supplies *what* (the owning team + the subdomain); Atlas
	owns placement, the fixed size, and the region/domain. We seed the Atlas tenant
	with the team owner's email on first use, then mirror the returned Pending row
	so the onboarding screen has something to poll immediately — the site.* events
	keep it fresh from there."""
	user = frappe.session.user
	team = resolve_team(user)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create sites for this team."), frappe.PermissionError)

	region = region or _default_region()
	client = AtlasClient.for_region(region)
	email = frappe.db.get_value("Team", team, "owner_user")
	site = client.create_site(team=team, subdomain=subdomain, email=email)

	from central.central.doctype.site.site import Site

	Site.mirror_site(client.instance.name, site)
	return {"name": site.get("name"), "fqdn": site.get("fqdn"), "status": site.get("status")}


@frappe.whitelist(methods=["GET"])
def get_site(name: str) -> dict:
	"""Current state of a site for the onboarding poll. Gated on team membership.

	Reads the mirror; while the site is still provisioning we pull Atlas's get_site
	as the self-heal (in case an event delivery was missed) and re-mirror. The
	one-click login URL + live URL are only surfaced once Running — the tenant
	handoff. The login URL is short-lived (a 24h session), so if the stored one has
	expired by the time the tenant lands here we regenerate a fresh one on read, so
	the link they click always works."""
	user = frappe.session.user
	mirror = frappe.db.get_value(
		"Site", name, ["team", "cluster", "status"], as_dict=True
	)
	if not mirror:
		frappe.throw(_("No site '{0}'.").format(name), frappe.DoesNotExistError)
	if mirror.team not in get_user_team_names(user):
		frappe.throw(_("You can't view this site."), frappe.PermissionError)

	if mirror.status not in _TERMINAL:
		from central.central.doctype.site.site import Site

		instance = frappe.get_doc("Atlas Instance", mirror.cluster)
		fresh = AtlasClient(instance).get_site(name)
		Site.mirror_site(mirror.cluster, fresh, synced_at=frappe.utils.now_datetime())
		mirror.status = fresh.get("status") or mirror.status

	doc = frappe.get_doc("Site", name)
	running = doc.status == "Running"
	return {
		"name": doc.name,
		"status": doc.status,
		"url": doc.url if running else None,
		"login_url": _fresh_site_login_url(doc) if running else None,
	}


def _fresh_site_login_url(doc) -> str | None:
	"""The site's usable one-click login URL: the stored one if it hasn't expired,
	else a freshly-regenerated one. The URL is a short-lived (24h) session, so a
	tenant who lands on a stale mirror row would otherwise get a dead link — we
	re-mint on read instead. Best-effort: if the regenerate call fails (Atlas
	unreachable), fall back to the stored URL rather than blocking the handoff."""
	if doc.login_url and not _login_url_expired(doc.login_url_expires_at):
		return doc.login_url
	try:
		return _regenerate_site_login(doc.name, doc.cluster).get("login_url") or doc.login_url
	except Exception:
		frappe.log_error(title=f"Regenerate login failed for site {doc.name}")
		return doc.login_url or None


def _login_url_expired(expires_at) -> bool:
	"""True if a stored login URL is at/past its expiry (or carries no expiry — treat
	an unstamped URL as unusable and force a regenerate). A small skew guard trims the
	tail so we don't hand out a URL that dies mid-click."""
	if not expires_at:
		return True
	skew = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=30)
	return frappe.utils.get_datetime(expires_at) <= skew


def _regenerate_site_login(name: str, cluster: str) -> dict:
	"""Ask Atlas to re-mint the site's login URL, re-mirror the fresh handoff, and
	return it. The Atlas Site controller re-signs the session in the guest and returns
	the Site-mirror shape; we upsert it so the stored URL + expiry stay in lockstep."""
	from central.central.doctype.site.site import Site

	instance = frappe.get_doc("Atlas Instance", cluster)
	fresh = AtlasClient(instance).regenerate_site_login(name)
	Site.mirror_site(cluster, fresh, synced_at=frappe.utils.now_datetime())
	return fresh


@frappe.whitelist(methods=["GET"])
def check_subdomain(subdomain: str, region: str | None = None) -> dict:
	"""Best-effort availability pre-check for the Name-your-site screen. Proxies the
	authoritative rules (label shape, reserved words, taken) to Atlas, which also
	returns the real FQDN suffix. Login-only — no team needed for a name check."""
	region = region or _default_region()
	return AtlasClient.for_region(region).check_subdomain(subdomain, region=region)


@frappe.whitelist(methods=["GET"])
def site_domain(region: str | None = None) -> dict:
	"""The region's root-domain suffix, so the UI can render `<sub>.<suffix>` before
	the user types. Atlas returns `domain` regardless of label validity."""
	region = region or _default_region()
	return {"domain": AtlasClient.for_region(region).check_subdomain("", region=region).get("domain")}
