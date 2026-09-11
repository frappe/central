# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""Central as Passport's provisioner.

Central registers each site it hands out with Passport, keeps the registration in step
with the site's address, and disables it when the site goes away. Sites never talk to
Passport's registration API themselves — they pull the finished registration from
Central through their own pilot (see `central.api.passport`).
"""

from __future__ import annotations

from functools import partial
from uuid import UUID, uuid5

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient, FrappeException
from frappe.integrations.frappe_providers.cloud_passport_enrollment import CALLBACK_PATH, login_uri
from frappe.integrations.openid_connect.urls import origin as url_origin

from central.central.doctype.central_passport_settings.central_passport_settings import (
	CentralPassportSettings,
)

# One stable Passport site id per Central site name. Deriving it rather than minting one
# is what makes registration idempotent: a call whose reply is lost leaves nothing written
# here, and the retry re-derives the same id, so Passport returns the registration it
# already made instead of a second one.
#
# It is a namespace, not a secret — like the namespaces RFC 4122 publishes. Knowing a site
# id grants nothing: every registration call is gated on the Passport Manager role.
#
# It must never change. A new namespace re-derives every id, so every existing site would
# look new to Passport and be registered twice. That is why it is a constant and not
# configuration: there is nothing here to tune, and nothing worth the risk of it differing
# between two deployments that share one Passport.
SITE_NAMESPACE = UUID("6cc73c09-0aac-4444-bdc8-f947a6379de0")

# The only states a site never comes back from. Everything else is a moment in a
# deploy, and taking sign-in away for one of those is an outage we caused.
GONE = ["Terminated"]

# Connect, then read. Passport is another web app, not a database: without this a hung
# one holds a Central worker until something else gives up first.
TIMEOUT = (5, 20)

# One reconcile pass calls Passport once per drifted site, so it is bounded rather than
# left to grow into a job that cannot finish.
RECONCILE_BATCH = 50

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

	One caller at a time per site. Re-addressing and rotating are two calls, and two
	pulls racing through them leave Passport holding the second secret while the site
	installs the first — sign-in broken until somebody asks again.
	"""
	settings = _settings()
	origin = _origin(site)
	operator = PassportOperator(settings)
	record = frappe.db.get_value(
		"Passport Registration",
		site["name"],
		["name", "client_id", "origin"],
		as_dict=True,
		for_update=True,
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
		# The site validates both endpoints and cannot know a development cluster runs
		# on plain http. Central already made that call to reach Passport at all.
		"allow_local_http": int(bool(settings.allow_local_http)),
	}


def on_site_update(doc, method=None):
	"""A terminated site must stop offering Frappe sign-in."""
	if doc.status not in GONE or not doc.has_value_changed("status"):
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
	"""Match registrations to whether their site still exists, both ways.

	The Terminated event is the fast path; this is the backstop for a missed one. Only a
	gone site closes a registration: reading "not Running" as gone took sign-in away
	from every site that was merely mid-deploy.

	It deliberately does not re-address a moved site. Re-addressing rotates the secret,
	and only the site's own pull can install the new one.
	"""
	settings = CentralPassportSettings.active()

	if not settings:
		return

	for record in drifted(enabled=1, status=GONE):
		set_enabled(record, settings, False)

	for record in drifted(enabled=0, status=["Running"]):
		set_enabled(record, settings, True)


def drifted(*, enabled: int, status: list[str]) -> list[frappe._dict]:
	"""Registrations out of step with their site, capped so one run cannot outlive its
	queue: each one costs a call to Passport, and the next run picks up the rest."""
	registration = frappe.qb.DocType("Passport Registration")
	site = frappe.qb.DocType("Site")

	return (
		frappe.qb.from_(registration)
		.join(site)
		.on(site.name == registration.site)
		.select(registration.name, registration.client_id, registration.origin, site.subdomain)
		.where((registration.enabled == enabled) & site.status.isin(status))
		.limit(RECONCILE_BATCH)
	).run(as_dict=True)


def disable(site_name: str):
	"""Stop Frappe sign-in for a site that is gone. Quiet when it was never registered."""
	record = frappe.db.get_value(
		"Passport Registration", site_name, ["name", "client_id", "origin", "enabled"], as_dict=True
	)
	settings = CentralPassportSettings.active()

	if record and record.enabled and settings:
		record.subdomain = frappe.db.get_value("Site", site_name, "subdomain")
		set_enabled(record, settings, False)


def set_enabled(record, settings, enabled: bool):
	"""Open or close one registration, leaving its address and title as they are."""
	PassportOperator(settings).readdress(
		record.client_id,
		title=_title({"name": record.name, "subdomain": record.subdomain}),
		origin=record.origin,
		enabled=enabled,
	)
	frappe.db.set_value("Passport Registration", record.name, "enabled", int(enabled))


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
		except FrappeException:
			frappe.log_error(title=f"Passport {method} failed")
			frappe.throw(_("Frappe sign-in could not {0}.").format(action), PassportError)
		except (OSError, ValueError):
			frappe.log_error(title=f"Passport {method} unreachable")
			frappe.throw(_("Frappe sign-in is unavailable right now."), PassportError)

	def _client(self) -> FrappeClient:
		client = FrappeClient(
			self.settings.issuer.rstrip("/"),
			api_key=self.settings.api_key,
			api_secret=self.settings.get_password("api_secret"),
		)
		# FrappeClient has no timeout of its own, and its session is the only place to
		# put one that every call it makes will honour.
		client.session.request = partial(client.session.request, timeout=TIMEOUT)

		return client


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
	"""Register Central itself as a Passport client.

	Central is a Passport client like any site — the same registration call, aimed at
	Central's own address. Safe to repeat: an unchanged registration returns the same
	secret. Who may then sign in is Central's own user list, matched on the first
	sign-in like on any other site.
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

	return {
		"provider": configure(
			issuer=settings.issuer.rstrip("/"),
			client_id=credentials["client_id"],
			client_secret=credentials["client_secret"],
			origin=origin,
			allow_local_http=bool(settings.allow_local_http),
		)
	}
