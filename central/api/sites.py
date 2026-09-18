from __future__ import annotations

import frappe
from frappe import _

from central.central.doctype.resource_action.resource_action import (
	PENDING_STATES,
	STATUS_FIELDS,
	action_status,
)
from central.central.doctype.site.site import Site
from central.errors import resource_action
from central.iam import can, resolve_team
from central.integrations.pilot import PilotLoginPending, is_site_reachable


@frappe.whitelist(methods=["GET"])
def site_domain(team: str | None = None) -> dict:
	"""The zone a new site is named in, so the console can show the suffix as they type."""
	from central.site_provisioning import trial_zone

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create sites for this Team."), frappe.PermissionError)

	return {"domain": trial_zone()}


@frappe.whitelist(methods=["GET"])
def check_subdomain(subdomain: str, team: str | None = None) -> dict:
	"""Whether a name is free, while the customer is still typing it."""
	from central.site_provisioning import subdomain_availability

	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw(_("You can't create sites for this Team."), frappe.PermissionError)

	return subdomain_availability(subdomain)


@frappe.whitelist(methods=["POST"])
@resource_action
def create_trial_site(subdomain: str, request_key: str, team: str | None = None) -> dict:
	"""Start a trial site under a name the customer chose. Gated on `server:create`."""
	from central.site_provisioning import create_trial_site as start

	return start(team, subdomain, request_key)


@frappe.whitelist(methods=["POST"])
@resource_action
def claim_site(name: str) -> dict:
	"""Hand back a way in and schedule the customer's hostname behind the response.

	The image name stays a valid Pilot alias after rename, so every login is minted against
	that stable name. A failed login leaves the site unclaimed for the console to retry. A
	successful login schedules the rename after commit and returns without waiting for it.

	Nothing here touches the machine's admin hostname. The region routes `admin-vm-*`
	statically and refuses to register it, so there is nothing for Central to claim."""
	site = authorized_site(name, "server:create")
	state = site_state(site)

	if state["login_url"]:
		site.mark_claimed()
	return state


@frappe.whitelist(methods=["GET"])
def get_site(name: str) -> dict:
	"""One site's state, and the sign-in URL once it answers on its own address."""
	return site_state(authorized_site(name, "server:view"))


@frappe.whitelist(methods=["GET"])
def onboarding_status(team: str | None = None) -> dict:
	"""What the signup funnel waits on: the team's site, or the creation still building it.

	The funnel cannot name the site it waits for, because the address follows from a
	machine the region has not built yet. So it asks about the team instead, which also
	lets a customer who reloads, or comes back later, rejoin the same wait."""
	user = frappe.session.user
	team = resolve_team(user, team)
	if not can(user, team, "server:view"):
		frappe.throw(_("You can't view this team's sites."), frappe.PermissionError)

	rows = frappe.get_list(
		"Resource Action",
		filters={
			"team": team,
			"requested_by": user,
			"resource_type": "Site",
			"action": "create",
		},
		fields=[*STATUS_FIELDS, "asset"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return {"site": None, "creation": None}

	creation = rows[0]
	name = frappe.db.get_value("Site", {"asset": creation.asset}, "name") if creation.asset else None
	if name:
		return {"site": site_state(frappe.get_doc("Site", name), with_login=False), "creation": None}

	return {
		"site": None,
		"creation": action_status(creation) if creation.status in (*PENDING_STATES, "Failed") else None,
	}


@frappe.whitelist(methods=["POST"])
@resource_action
def terminate_site(name: str) -> dict:
	"""Terminate a site by terminating the machine it is. Gated on `server:terminate`."""
	from central.resource_actions import submit_command

	site = authorized_site(name, "server:terminate")
	return submit_command("terminate", site.team, site.asset)


def site_state(site: Site, with_login: bool = True) -> dict:
	"""Nothing is provisioned during signup, so readiness is not a build finishing: it is
	the machine being awake and the site answering.

	Minting a session is not part of that question and must not ride on it. It starts a
	Frappe process on the machine and creates a real Administrator session, so a poll that
	minted one would open a session a second and wait on a cold VM to do it."""
	status = site.status
	ready = status == "Running" and is_site_reachable(site.url)
	login_url = None
	login_pending = False
	if ready and with_login:
		try:
			login_url = site.get_login_url()
		except PilotLoginPending:
			login_pending = True

	return {
		"name": site.name,
		"status": status,
		"url": site.url,
		"ready": ready,
		"login_url": login_url,
		"login_pending": login_pending,
	}


def authorized_site(name: str, capability: str) -> Site:
	"""The Site document, once the caller holds `capability` in the Team that owns it."""
	team = frappe.db.get_value("Site", name, "team")
	if not team:
		frappe.throw(_("No site '{0}'.").format(name), frappe.DoesNotExistError)
	if not can(frappe.session.user, team, capability):
		frappe.throw(_("You can't manage this site."), frappe.PermissionError)

	site = frappe.get_doc("Site", name)
	site.check_permission("read")
	return site
