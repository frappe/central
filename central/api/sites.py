import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils.translations import _lt

from central.errors import handle_resource_operation
from central.iam import can
from central.infrastructure.doctype.resource_action.resource_action import (
	PENDING_STATES,
	STATUS_FIELDS,
	action_status,
)
from central.infrastructure.doctype.site.site import Site
from central.integrations.pilot import PilotLoginPending, is_site_reachable
from central.signups.journey import ACTION_FIELDS, SetupJourney
from central.utils.guards import require_capability


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:create", _lt("You can't create sites for this Team. Ask a team admin to review your access.")
)
def site_domain(team: str | None = None, product: str | None = None) -> dict:
	"""The zone a new site of this product is named in, so the console can show the suffix as
	they type. It is the zone of the region that the trial is then created in."""
	from central.signups.doctype.product.product import get_signup_product
	from central.site_provisioning import trial_zone

	signup_product = get_signup_product(product) if product else None
	return {"domain": trial_zone(team, signup_product)}


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:create", _lt("You can't create sites for this Team. Ask a team admin to review your access.")
)
def get_open_trial(team: str | None = None) -> dict | None:
	"""The owner's open free trial, so the signup page offers that site before it asks for a new one."""
	from central.signups.eligibility import get_open_trial_summary

	return get_open_trial_summary(team)


@frappe.whitelist(methods=["POST"])
@require_capability(
	"server:create", _lt("You can't create sites for this Team. Ask a team admin to review your access.")
)
def install_trial_app(product: str, team: str | None = None) -> dict:
	"""Install a product's app on the owner's open trial site, instead of a second free trial.
	Returns `site`, the bench's name for it, and `task_id` for `get_trial_app_install`."""
	from central.signups.app_install import TrialAppInstall

	return TrialAppInstall(authorized_open_trial(team), product).start()


# A POST, because a failed install leaves its reason on the Site and Frappe rolls back a GET.
@frappe.whitelist(methods=["POST"])
@require_capability(
	"server:create", _lt("You can't create sites for this Team. Ask a team admin to review your access.")
)
def get_trial_app_install(site: str, task_id: str, product: str, team: str | None = None) -> dict:
	"""The progress of an app install on the owner's open trial site. See `TrialAppInstall.get_progress`."""
	from central.signups.app_install import TrialAppInstall

	return TrialAppInstall(authorized_open_trial(team), product).get_progress(site, task_id)


def authorized_open_trial(team: str):
	"""The owner's open trial, once the caller may sign in to its site. It may be on another team of the owner."""
	from central.signups.eligibility import get_open_trial_of_owner
	from central.signups.trial import Trial

	trial = get_open_trial_of_owner(team)
	if not trial:
		frappe.throw(_("You have no free trial site to add an app to."))

	return Trial(authorized_site(trial.site.name, "server:console"))


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:create", _lt("You can't create sites for this Team. Ask a team admin to review your access.")
)
def check_subdomain(subdomain: str, team: str | None = None) -> dict:
	"""Whether a name is free, while the customer is still typing it."""
	from central.site_provisioning import subdomain_availability

	return subdomain_availability(subdomain)


@frappe.whitelist(methods=["POST"])
def create_trial_team(
	utm_source: str | None = None,
	utm_medium: str | None = None,
	utm_campaign: str | None = None,
	referrer: str | None = None,
	product: str | None = None,
) -> dict:
	"""Give a caller with no team a team before the trial funnel asks for a site name. The
	browser sends how the signup first arrived, which the new team keeps."""
	from central.site_provisioning import create_trial_team as create

	attribution = {
		"utm_source": utm_source,
		"utm_medium": utm_medium,
		"utm_campaign": utm_campaign,
		"referrer": referrer,
		"product": product,
	}

	return {"team": create(frappe.session.user, attribution)}


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def create_trial_site(
	subdomain: str,
	request_key: str,
	product: str,
	team: str | None = None,
) -> dict:
	"""Start a product's trial site under a name the customer chose. Gated on `server:create`."""
	from central.site_provisioning import create_trial_site as start

	return start(team, subdomain, request_key, product)


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def claim_site(name: str) -> dict:
	"""Return a login for the new site and schedule its rename to the customer's hostname.
	A failed login leaves the site unclaimed, so the console can try again."""
	site = authorized_site(name, "server:console")
	state = site_state(site)

	if state["login_url"]:
		site.mark_claimed()

	return state


# nosemgrep: guest-whitelisted-method -- the signed link is checked in PlanChange.from_signed_link.
@frappe.whitelist(allow_guest=True, methods=["GET"])
# Counted per link, not per address: one open page polls about 20 times a minute, and many
# people behind one office address can each follow their own change.
@rate_limit(key="action", limit=60, seconds=60, ip_based=False)
def plan_change_progress(action: str, site: str, signature: str) -> dict:
	"""Progress of a site's plan change, for the public waiting page."""
	from central.infrastructure.doctype.site.plan_change import PlanChange

	return PlanChange.from_signed_link(action, site, signature).get_progress()


@frappe.whitelist(methods=["GET"])
def get_site(name: str) -> dict:
	"""Return one site's state without creating a remote Administrator session."""
	return site_state(authorized_site(name, "server:view"), with_login=False)


@frappe.whitelist(methods=["POST"])
def login_site(name: str, product: str | None = None) -> dict:
	"""Create a one-time site login. It signs in as Administrator, so it needs `server:console`.
	It lands on the page of `product` when given, such as an app just installed on the site."""
	return site_state(authorized_site(name, "server:console"), with_login=True, product=product)


@frappe.whitelist(methods=["GET"])
@require_capability(
	"server:view", _lt("You can't view this team's sites. Ask a team admin to review your access.")
)
def onboarding_status(team: str | None = None, product: str | None = None) -> dict:
	"""Resume this product's site or creation within the authorized team, with the journey the
	waiting page follows."""
	site, action = find_onboarding(team, product)
	state = site_state(site, with_login=False) if site else None
	creation = (
		action_status(action)
		if not site and action and action.status in (*PENDING_STATES, "Failed", "Timed Out")
		else None
	)
	if not state and not creation:
		return {"site": None, "creation": None, "journey": None}

	journey = SetupJourney(action, site, state)
	return {"site": state, "creation": creation, "journey": journey.as_dict()}


def find_onboarding(team: str | None, product: str | None) -> tuple[Site | None, frappe._dict | None]:
	"""The signup's site, once it exists, and the creation request that started it."""
	if product:
		if not frappe.db.exists("Product", product):
			frappe.throw(_("This product is not available for signup."))
		sites = frappe.get_list(
			"Site",
			filters={"team": team, "product": product, "server.status": ["!=", "Terminated"]},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		if sites:
			site = authorized_site(sites[0], "server:view")
			return site, latest_creation({"team": team, "server": site.server})

	action = latest_creation(
		{"team": team, "requested_by": frappe.session.user, "product": product or ["is", "not set"]}
	)
	name = (
		frappe.db.get_value("Site", {"server": action.server}, "name") if action and action.server else None
	)
	if not name:
		return None, action

	site = authorized_site(name, "server:view")
	if site.status == "Terminated":
		return None, None
	return site, action


def latest_creation(filters: dict) -> frappe._dict | None:
	rows = frappe.get_list(
		"Resource Action",
		filters={**filters, "resource_type": "Site", "action": "create"},
		fields=list({*STATUS_FIELDS, *ACTION_FIELDS}),
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None


@frappe.whitelist(methods=["POST"])
@handle_resource_operation
def terminate_site(name: str) -> dict:
	"""Terminate a site by terminating the machine it is. Gated on `server:terminate`."""
	from central.resource_actions import submit_command

	site = authorized_site(name, "server:terminate")

	return submit_command("terminate", site.team, site.server)


def site_state(site: Site, with_login: bool = True, product: str | None = None) -> dict:
	"""The site's readiness: its machine is awake and the site answers.
	A login is minted only when asked, because each one starts a real Administrator session.
	Only the POST calls that ask for a login record readiness, because Frappe rolls back a GET."""
	status = site.status
	ready = is_site_reachable(site.url)
	if ready and with_login:
		site.record_ready()
	login_url = None
	# A busy machine can miss one probe, so a login it could not try yet is retried, not failed.
	login_pending = with_login and not ready
	if ready and with_login:
		try:
			login_url = site.get_login_url(frappe.session.user, product)
		except PilotLoginPending:
			login_pending = True

	return {
		"name": site.name,
		"status": status,
		"url": site.primary_url,
		"ready": ready,
		"login_url": login_url,
		"login_pending": login_pending,
		"claimed": bool(site.claimed_at),
	}


def authorized_site(name: str, capability: str) -> Site:
	"""The Site document, once the caller holds `capability` on the server the site runs on."""
	row = frappe.db.get_value("Site", name, ["team", "server"], as_dict=True)
	# One answer for a missing site and a foreign one, so a name cannot be probed.
	if not row or not row.team or not can(frappe.session.user, row.team, capability, server=row.server):
		frappe.throw(
			_("You can't manage this site. Ask a team admin to review your access."), frappe.PermissionError
		)

	site = frappe.get_doc("Site", name)
	site.check_permission("read")

	return site
