from __future__ import annotations

import frappe
from frappe import _

from central.api.site_login import site_login_url
from central.central.doctype.resource_action.resource_action import open_action
from central.errors import resource_action
from central.iam import can, get_user_team_names, resolve_team
from central.integrations.atlas import AtlasClient, AtlasResourceGone

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
@resource_action
def create_site(subdomain: str, region: str | None = None) -> dict:
	"""Provision a self-serve site for the user's team. Gated on `server:create`.

	Server is the atomic unit, so deploying a site is authorized by the same
	provisioning capability as standing up a server (site-level capabilities are
	deferred). Central supplies *what* (the owning team + the subdomain); Atlas
	owns placement, the fixed size, and the region/domain. Atlas get-or-creates the
	tenant (keyed on the team) and returns the Pending row, which we mirror so the
	onboarding screen has something to poll immediately — the site.* events keep it
	fresh from there."""
	user = frappe.session.user
	team = resolve_team(user)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create sites for this team."), frappe.PermissionError)

	region = region or _default_region()
	client = AtlasClient.for_region(region)

	# site create is async (clone→deploy→route runs on Atlas after this returns). A
	# rejection surfaces as an envelope and leaves no row; we open the tracking action
	# only once Atlas has accepted the create.
	correlation_id = frappe.generate_hash()
	site = client.create_site(team=team, subdomain=subdomain, correlation_id=correlation_id)

	from central.central.doctype.site.site import Site

	Site.mirror_site(client.instance.name, site)
	open_action("Site", "create", team=team, resource_id=site.get("name"), correlation_id=correlation_id)

	return {
		"name": site.get("name"),
		"fqdn": site.get("fqdn"),
		"status": site.get("status"),
		"action": correlation_id,
	}


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
	mirror = frappe.db.get_value("Site", name, ["team", "cluster", "status"], as_dict=True)
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
		"login_url": site_login_url(doc) if running else None,
	}


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


@frappe.whitelist(methods=["POST"])
@resource_action
def terminate_site(name: str) -> dict:
	"""Terminate a self-serve site (and its 1:1 backing VM). Gated on `server:terminate` —
	a site is a VM, so removing it is authorized like tearing down a server (site-level
	capabilities are deferred). The mirror flips to Terminated on the site.* event."""
	user = frappe.session.user
	site = frappe.db.get_value("Site", name, ["team", "cluster", "status"], as_dict=True)
	if not site:
		frappe.throw(_("Unknown site {0}.").format(name))
	if not can(user, site.team, "server:terminate"):
		frappe.throw(_("You can't terminate this team's sites."), frappe.PermissionError)

	# Already gone — no-op, and never issue a second teardown to Atlas.
	if site.status == "Terminated":
		return {"name": name, "status": site.status}
	# A site with no backing region was never placed on Atlas; without this,
	# get_doc("Atlas Instance", None) below raises an opaque error.
	if not site.cluster:
		frappe.throw(_("Site {0} has no backing region to terminate.").format(name), frappe.ValidationError)

	instance = frappe.get_doc("Atlas Instance", site.cluster)

	# Open the tracking action only once Atlas accepts. A rejection surfaces as an envelope
	# (via @resource_action) and leaves no row to strand.
	correlation_id = frappe.generate_hash()
	try:
		AtlasClient(instance).terminate_site(name, correlation_id=correlation_id)
	except AtlasResourceGone:
		# Already gone on Atlas (e.g. a stale mirror row) — terminate is idempotent: reflect
		# it on the mirror and record a Succeeded action rather than a scary "region down".
		frappe.get_doc("Site", name).db_set("status", "Terminated", notify=True)
		open_action(
			"Site", "terminate", team=site.team, resource_id=name,
			correlation_id=correlation_id, status="Succeeded",
		)
		return {"name": name, "status": "Terminated", "action": correlation_id}

	open_action("Site", "terminate", team=site.team, resource_id=name, correlation_id=correlation_id)

	return {"name": name, "status": "Terminating", "action": correlation_id}
