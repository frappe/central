# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Central as Passport's provisioner.

Central registers each site it hands out with Passport, keeps the registration in step
with the site's address, and disables it when the site goes away. Sites never talk to
Passport's registration API themselves — they pull the finished registration from
Central through their own pilot (see `central.api.passport`).
"""

from __future__ import annotations

from uuid import UUID, uuid5

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient, FrappeException
from frappe.integrations.frappe_providers.cloud_passport_enrollment import CALLBACK_PATH, login_uri
from frappe.integrations.openid_connect.urls import origin as url_origin

from central.central.doctype.central_passport_settings.central_passport_settings import (
	CentralPassportSettings,
)

# One stable Passport site id per Central site name. Deriving it means registration is
# idempotent without Central having to mint and remember a UUID before its first call.
SITE_NAMESPACE = UUID("6cc73c09-0aac-4444-bdc8-f947a6379de0")

# Where a site receives sign-out notices. Passport requires it, and validates it against
# the origin, so Central names it rather than letting Passport guess a core route.
LOGOUT_PATH = "/api/method/frappe.integrations.openid_connect.logout.receive"


class PassportError(frappe.ValidationError):
	"""Passport is unreachable or refused a registration change."""


def site_id(site: str) -> str:
	return str(uuid5(SITE_NAMESPACE, site))


def registration_for(site: dict) -> dict:
	"""The registration this site should install, created on first ask.

	A site that moved to another address is re-addressed and given a fresh secret, so a
	stale callback URL can never keep working.
	"""
	settings = _settings()
	origin = _origin(site)
	operator = PassportOperator(settings)
	record = frappe.db.get_value(
		"Passport Registration", site["name"], ["name", "client_id", "origin"], as_dict=True
	)

	if record and record.origin != origin:
		operator.readdress(record.client_id, title=_title(site), origin=origin)
		credentials = operator.rotate(record.client_id)
	else:
		credentials = operator.register(site_id=site_id(site["name"]), title=_title(site), origin=origin)

	_remember(site, origin, credentials)

	return {
		"issuer": settings.issuer.rstrip("/"),
		"site_id": credentials["site_id"],
		"client_id": credentials["client_id"],
		"client_secret": credentials["client_secret"],
		"origin": origin,
	}


def on_site_update(doc, method=None):
	"""A terminated site must stop offering Frappe sign-in."""
	if doc.status != "Terminated" or not doc.has_value_changed("status"):
		return
	if not frappe.db.exists("Passport Registration", doc.name):
		return

	frappe.enqueue(
		"central.integrations.passport.disable",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"passport-disable-{doc.name}",
		deduplicate=True,
		site_name=doc.name,
	)


def reconcile():
	"""Disable registrations for sites that are no longer running.

	The Terminated event is the fast path; this is the backstop that corrects a missed
	one, the same shape as the Atlas mirror's reconcile.

	It deliberately does not re-address a moved site. Re-addressing rotates the secret,
	and only the site's own pull can install the new one — doing it here would leave the
	site holding a secret Passport no longer accepts.
	"""
	registration = frappe.qb.DocType("Passport Registration")
	site = frappe.qb.DocType("Site")
	stale = (
		frappe.qb.from_(registration)
		.join(site)
		.on(site.name == registration.site)
		.select(registration.site)
		.where((registration.enabled == 1) & (site.status != "Running"))
	).run(pluck=True)

	for site_name in stale:
		disable(site_name)


def disable(site_name: str):
	"""Stop Frappe sign-in for a site that is gone. Quiet when it was never registered."""
	record = frappe.db.get_value(
		"Passport Registration", site_name, ["name", "client_id", "origin", "enabled"], as_dict=True
	)
	settings = CentralPassportSettings.active()

	if not record or not record.enabled or not settings:
		return

	PassportOperator(settings).readdress(
		record.client_id, title=_title({"name": site_name}), origin=record.origin, enabled=False
	)
	frappe.db.set_value("Passport Registration", record.name, "enabled", 0)


class PassportOperator:
	"""Passport's registration API, called with Central's Passport Manager credentials."""

	def __init__(self, settings):
		self.settings = settings

	def register(self, *, site_id: str, title: str, origin: str) -> dict:
		return self._call(
			"passport.registration.register_site",
			{
				"site_id": site_id,
				"title": title,
				"origin": origin,
				"login_uri": login_uri(origin),
				"redirect_uri": origin + CALLBACK_PATH,
				"backchannel_logout_uri": origin + LOGOUT_PATH,
			},
			action="register this site",
		)

	def readdress(self, client_id: str, *, title: str, origin: str, enabled: bool = True) -> dict:
		return self._call(
			"passport.registration.update_site",
			{
				"client_id": client_id,
				"title": title,
				"origin": origin,
				"login_uri": login_uri(origin),
				"redirect_uri": origin + CALLBACK_PATH,
				"backchannel_logout_uri": origin + LOGOUT_PATH,
				"enabled": int(enabled),
			},
			action="update this registration",
		)

	def rotate(self, client_id: str) -> dict:
		return self._call(
			"passport.registration.rotate_secret", {"client_id": client_id}, action="issue a new secret"
		)

	def _call(self, method: str, params: dict, *, action: str) -> dict:
		try:
			return self._client().post_api(method, params=params)
		except FrappeException as exception:
			frappe.log_error(title=f"Passport {method} failed", message=str(exception))
			frappe.throw(_("Frappe sign-in could not {0}.").format(action), PassportError)
		except Exception:
			frappe.log_error(title=f"Passport {method} unreachable")
			frappe.throw(_("Frappe sign-in is unavailable right now."), PassportError)

	def _client(self) -> FrappeClient:
		return FrappeClient(
			self.settings.issuer.rstrip("/"),
			api_key=self.settings.api_key,
			api_secret=self.settings.get_password("api_secret"),
		)


def _settings():
	settings = CentralPassportSettings.active()

	if not settings:
		frappe.throw(_("Frappe sign-in is not configured."), PassportError)

	return settings


def _origin(site: dict) -> str:
	if site.get("status") != "Running" or not site.get("url"):
		frappe.throw(_("A site can only get Frappe sign-in once it is running."), PassportError)

	origin = url_origin(site["url"])

	if not origin or origin != site["url"].rstrip("/"):
		frappe.throw(_("This site has no usable address yet."), PassportError)

	return origin


def _title(site: dict) -> str:
	return (site.get("subdomain") or site["name"]).replace("-", " ").title()


def _remember(site: dict, origin: str, credentials: dict):
	values = {
		"team": site["team"],
		"site_id": credentials["site_id"],
		"client_id": credentials["client_id"],
		"origin": origin,
		"enabled": 1,
		"registered_at": frappe.utils.now_datetime(),
	}

	if frappe.db.exists("Passport Registration", site["name"]):
		frappe.db.set_value("Passport Registration", site["name"], values)
	else:
		frappe.get_doc(doctype="Passport Registration", site=site["name"], **values).insert()


def connect_central() -> dict:
	"""Register Central itself as a Passport client and link the operator doing it.

	Central is a Passport client like any site — the same registration call, aimed at
	Central's own address. Safe to repeat: an unchanged registration returns the same
	secret.

	Installing the registration alone put a "Continue with Frappe" button on the sign-in
	page that then refused every login, because a sign-in needs an identity link and
	nothing had created one. So this links the operator running it too — and reports what
	it linked, because Administrator can never hold a Frappe identity and an operator
	signed in as one still has to name who may sign in, with link_cloud_users.
	"""
	from frappe.integrations.frappe_providers.cloud_passport_enrollment import configure

	from central.sso import central_url

	frappe.only_for("System Manager")
	settings = _settings()
	origin = url_origin(central_url())

	if origin == settings.issuer.rstrip("/"):
		frappe.throw(_("Central cannot be its own identity provider."), PassportError)

	credentials = PassportOperator(settings).register(
		site_id=site_id(frappe.local.site), title="Frappe Cloud", origin=origin
	)
	provider = configure(
		issuer=settings.issuer.rstrip("/"),
		site_id=credentials["site_id"],
		client_id=credentials["client_id"],
		client_secret=credentials["client_secret"],
		origin=origin,
		allow_local_http=bool(settings.allow_local_http),
	)
	linked, pending = link_cloud_users([frappe.session.user])

	return {"provider": provider, "linked": linked, "pending": pending}


def link_cloud_users(emails: list[str]) -> tuple[list[str], list[str]]:
	"""Let named Central users sign in with their Frappe identity.

	Returns the addresses linked and those with no Frappe identity yet. Links made here
	are unmanaged: a later sync must never withdraw something an operator did by hand.
	"""
	from frappe.integrations.frappe_providers.cloud_passport_memberships import link_users

	frappe.only_for("System Manager")
	users = {}

	for email in emails or []:
		address = (email or "").strip().lower()
		user = frappe.db.get_value("User", {"email": address, "enabled": 1}, "name")

		if user and user not in ("Administrator", "Guest"):
			users[address] = user

	return link_users(users) if users else ([], [])


def on_team_update(doc, method=None):
	"""A new team member should be able to sign in with their Frappe identity.

	Enqueued, because linking asks the identity service who someone is and accepting an
	invitation must not fail when that service is briefly unreachable.
	"""
	if not CentralPassportSettings.active() or not frappe.db.exists("OpenID Connect Provider", "Passport"):
		return

	# Every team save reaches here, and enqueued work runs inline under test — which would
	# make each one call the identity service. Tests drive link_team_members directly.
	if frappe.flags.in_test or frappe.flags.in_migrate or frappe.flags.in_install:
		return

	frappe.enqueue(
		"central.integrations.passport.link_team_members",
		queue="short",
		enqueue_after_commit=True,
		job_id=f"passport-link-team-{doc.name}",
		deduplicate=True,
		team=doc.name,
	)


def link_team_members(team: str) -> tuple[list[str], list[str]]:
	"""Give a team's active members Frappe sign-in on Central, where they have identities.

	Central never brings an identity into existence. Someone who has not signed in to
	Frappe ID yet is reported pending and picked up by the reconcile once they have, which
	is what makes "no Frappe ID yet" a waiting state rather than a dead end.
	"""
	member = frappe.qb.DocType("Team Member")
	user = frappe.qb.DocType("User")
	emails = (
		frappe.qb.from_(member)
		.join(user)
		.on(user.name == member.user)
		.select(user.email)
		.distinct()
		.where(
			(member.parenttype == "Team")
			& (member.parentfield == "members")
			& (member.parent == team)
			& (member.status == "Active")
			& (user.enabled == 1)
		)
	).run(pluck=True)

	return link_cloud_users(emails) if emails else ([], [])


def link_unlinked_members() -> list[str]:
	"""Link every active team member who has since gained a Frappe identity.

	The team event is the fast path; this is what eventually links someone who was invited
	before they had signed in to Frappe ID at all.
	"""
	if not CentralPassportSettings.active() or not frappe.db.exists("OpenID Connect Provider", "Passport"):
		return []

	member = frappe.qb.DocType("Team Member")
	teams = (
		frappe.qb.from_(member)
		.select(member.parent)
		.distinct()
		.where(
			(member.parenttype == "Team") & (member.parentfield == "members") & (member.status == "Active")
		)
	).run(pluck=True)
	linked = []

	for team in teams:
		linked.extend(link_team_members(team)[0])

	return linked
