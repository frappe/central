import re
import secrets
from urllib.parse import urlencode, urlparse

import frappe
import jwt
from frappe import _
from frappe.query_builder.functions import GroupConcat
from frappe.utils import add_days, flt, now_datetime, validate_email_address
from frappe.utils.verified_command import get_secret

from central.errors import PartnersDisabledError
from central.iam import get_owned_team_names, is_team_owner
from central.identity.doctype.team_invitation.team_invitation import get_expiry_days
from central.sso import central_url

PARTNER_CODE_PREFIX_LENGTH = 3
PARTNER_CODE_DIGITS = 5
PARTNER_CODE_ATTEMPTS = 10
# The audience keeps a registration token from passing as any other token signed with the site secret.
REGISTRATION_AUDIENCE = "central:partner-registration"


def generate_partner_code(team_name: str) -> str:
	"""A new partner code, such as `TRI-48213`: three letters of the team name and five
	random digits. The unique constraint on `Team.partner_code` is the final guard."""
	letters = re.sub(r"[^A-Za-z]", "", team_name).upper()
	prefix = letters[:PARTNER_CODE_PREFIX_LENGTH].ljust(PARTNER_CODE_PREFIX_LENGTH, "P")

	for _attempt in range(PARTNER_CODE_ATTEMPTS):
		digits = str(secrets.randbelow(10**PARTNER_CODE_DIGITS)).zfill(PARTNER_CODE_DIGITS)
		code = f"{prefix}-{digits}"
		if not frappe.db.exists("Team", {"partner_code": code}):
			return code

	frappe.throw(_("Could not generate a unique partner code. Try again."))


def get_partner_team(connect_partner_id: str) -> frappe._dict | None:
	"""The team that represents a Connect partner, with its partner code."""
	return frappe.db.get_value(
		"Team",
		{"connect_partner_id": connect_partner_id},
		["name", "partner_code"],
		as_dict=True,
	)


def require_partners_enabled() -> None:
	"""Refuse to start a new partner or partner link while Central Settings has partners off.
	Partners and links that exist keep working."""
	if not frappe.db.get_single_value("Central Settings", "enable_partners"):
		frappe.throw(_("Frappe partners are not available on Frappe Cloud yet."), PartnersDisabledError)


def get_registration_status(connect_partner_id: str) -> dict:
	"""Completed, with the team, its code, and the Frappe Cloud pages Connect links to, once a
	team represents the partner. Else Pending. Central owns its routes, so Connect never builds
	one."""
	team = get_partner_team(connect_partner_id)
	if not team:
		return {"status": "Pending"}

	return {
		"status": "Completed",
		"team": team.name,
		"partner_code": team.partner_code,
		"add_partner_url": f"{central_url()}/dashboard/partner?{urlencode({'code': team.partner_code})}",
		"invoices_url": f"{central_url()}/dashboard/billing/invoices",
	}


def request_registration(
	connect_partner_id: str, partner_name: str, owner_email: str, return_url: str | None = None
) -> dict:
	"""A link where the partner's owner chooses its team. It is a signed token, so Central stores
	nothing until the owner completes it."""
	status = get_registration_status(connect_partner_id)
	if status["status"] == "Completed":
		return status

	require_partners_enabled()
	validate_return_url(return_url)
	claims = {
		"aud": REGISTRATION_AUDIENCE,
		"sub": connect_partner_id,
		"name": partner_name,
		"email": validate_email_address(owner_email.strip().lower(), throw=True),
		"return_url": return_url or None,
		"exp": add_days(now_datetime(), get_expiry_days()),
	}
	token = jwt.encode(claims, get_secret(), algorithm="HS256")
	return {"status": "Pending", "url": f"{central_url()}/dashboard/partner-registration/{token}"}


def read_registration(token: str) -> dict:
	"""The claims of a registration token, after its signature and expiry are checked."""
	try:
		return jwt.decode(token, get_secret(), algorithms=["HS256"], audience=REGISTRATION_AUDIENCE)
	except jwt.PyJWTError:
		frappe.throw(
			_(
				"This registration link is not valid or has expired. Open the latest link from Frappe Connect."
			),
			frappe.DoesNotExistError,
		)


def get_registration_summary(token: str) -> dict:
	"""What the registration page shows. The owner also gets the teams they can choose."""
	claims = read_registration(token)
	summary = {
		"partner_name": claims["name"],
		"owner_email": claims["email"],
		"status": get_registration_status(claims["sub"])["status"],
		"has_account": bool(frappe.db.exists("User", claims["email"])),
		"teams": [],
	}
	if frappe.session.user == claims["email"]:
		summary["teams"] = get_registrable_teams(claims["email"])

	return summary


def complete_registration(token: str, team: str) -> dict:
	"""Make `team` the partner's team.

	1. The token must be signed by Central and not expired.
	2. The signed-in user must be the owner email in the token.
	3. The user must own the team, and the team must be Active.
	4. The partner must not have a team, and the team must not represent a partner."""
	claims = read_registration(token)
	completion = {"team": team, "return_url": claims["return_url"]}
	current = get_partner_team(claims["sub"])
	if current and current.name == team:
		return completion

	user = frappe.session.user
	if user != claims["email"]:
		frappe.throw(
			_("This link is for {0}. Sign in with that email to continue.").format(claims["email"]),
			frappe.PermissionError,
		)
	if not is_team_owner(user, team):
		frappe.throw(_("Choose a team that you own."), frappe.PermissionError)
	if current:
		frappe.throw(_("This partner already has a Frappe Cloud team."))

	frappe.get_doc("Team", team).register_as_partner(claims["sub"])
	return completion


def get_registrable_teams(user: str) -> list[dict]:
	"""The Active teams that `user` owns and that do not represent a partner yet."""
	owned = get_owned_team_names(user)
	if not owned:
		return []

	return frappe.get_all(
		"Team",
		filters={"name": ("in", owned), "connect_partner_id": ("is", "not set")},
		fields=["name", "team_name"],
		order_by="team_name",
	)


def validate_return_url(return_url: str | None) -> None:
	"""A return URL must be on the Connect host, so the registration page cannot be an open redirect."""
	if not return_url:
		return

	connect_url = frappe.db.get_single_value("Central Settings", "connect_url")
	if not connect_url:
		frappe.throw(_("Set the Connect URL in Central Settings before Connect sends a return URL."))

	connect_host = urlparse(connect_url).hostname
	parsed = urlparse(return_url)
	if parsed.scheme not in ("http", "https") or parsed.hostname != connect_host:
		frappe.throw(_("The return URL must be on the Connect host {0}.").format(connect_host))


def end_team_links(team: str, reason: str) -> None:
	"""End every Active link where `team` is the customer or the partner."""
	for name in frappe.get_all(
		"Partner Link",
		filters=[["status", "=", "Active"]],
		or_filters=[["customer_team", "=", team], ["partner_team", "=", team]],
		pluck="name",
	):
		link = frappe.get_doc("Partner Link", name)
		# A team closing or leaving the program ends its links; the caller checked who may.
		link.flags.ignore_permissions = True
		link.end(reason)


def get_customer_hosting(teams: list[str]) -> dict[str, dict]:
	"""For Connect: each team's currency, monthly recurring revenue, and servers with their
	sites. The MRR is billing's committed run rate, before tax."""
	from central.billing.catalog.subscriptions import active_segments, team_run_rate
	from central.billing.doctype.billing_profile.billing_profile import get_team_currency

	if not teams:
		return {}

	hosting = {
		team: {"currency": get_team_currency(team), "mrr": team_run_rate(team), "servers": []}
		for team in teams
	}
	rates = {
		segment.server_id: segment.locked_rate
		for segment in active_segments({"team": ("in", teams), "enabled": 1})
		if segment.server_id
	}
	for server in _get_servers_with_sites(teams):
		hosting[server.team]["servers"].append(
			{
				"name": server.title,
				"plan": server.plan,
				"amount": flt(rates.get(server.name)),
				"status": server.status,
				"region": server.region,
				"sites": server.sites.split(",") if server.sites else [],
			}
		)

	return hosting


def _get_servers_with_sites(teams: list[str]) -> list[frappe._dict]:
	server = frappe.qb.DocType("Virtual Machine")
	plan = frappe.qb.DocType("Plan")
	site = frappe.qb.DocType("Site")

	return (
		frappe.qb.from_(server)
		.left_join(plan)
		.on(plan.name == server.plan)
		.left_join(site)
		.on(site.server == server.name)
		.select(
			server.name,
			server.team,
			server.title,
			plan.title.as_("plan"),
			server.status,
			server.region,
			GroupConcat(site.site_name).as_("sites"),
		)
		.where(server.team.isin(teams) & (server.status != "Terminated"))
		.groupby(server.name)
		.orderby(server.title)
	).run(as_dict=True)
