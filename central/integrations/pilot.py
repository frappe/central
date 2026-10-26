from __future__ import annotations

import json
from urllib.parse import quote, urlparse

import frappe
import requests
from frappe import _

from central.api.jwks import jwks_document
from central.api.pilot import get_telemetry_base_url, region_id_of
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.user_mail_account.user_mail_account import UserMailAccount
from central.sso import central_url, jwks_url, mint_bench_login, mint_datum_token, mint_site_login

PILOT_TASK_TIMEOUT_SECONDS = 35
# Minting a session can start a cold Frappe process on the machine. Central waits long
# enough for that process rather than discarding a session the machine creates later.
SITE_LOGIN_TIMEOUT_SECONDS = 120
SITE_PING_TIMEOUT_SECONDS = 4


def get_bootstrap_metadata(action) -> dict[str, str]:
	"""Mint the credential for a Pilot creation and return its guest metadata values."""
	# A Pilot seeded with an empty key set could never verify a Central login.
	initial_jwks = jwks_document()
	if not initial_jwks["keys"]:
		frappe.throw(_("Initialize the Pilot signing key in Central SSO Settings before creating a server."))

	credential = f"pilot-{action.name}"
	token = PilotCredential.mint(action.team, credential, audience_id=credential)
	action.db_set("credential", credential)
	bootstrap = {
		"central_endpoint": central_url(),
		"central_auth_token": token,
		"jwks_url": jwks_url(),
		"jwks_audience_id": credential,
		# The keys travel with the credential, so the first token needs no fetch and a boot
		# before Central is reachable still verifies.
		"initial_jwks_cache": initial_jwks,
	}

	# Metal caps each metadata value at 1 KiB. Pilot merges pilot-common-config into
	# common_config.toml and pilot-common-site-config into common_site_config.json at bootstrap.
	metadata = {"pilot-central": json.dumps(bootstrap)}
	# Frappe's Pulse telemetry files a site's events under `fc_team`, so the events of a
	# product on this server join the team's signup funnel in Central.
	common_site_config = frappe.get_cached_doc("Central Settings").get_common_site_config() | {
		"fc_team": action.team
	}
	if mailbox := UserMailAccount.assign(action):
		common_site_config |= mailbox.get_site_config()
	metadata["pilot-common-site-config"] = json.dumps(common_site_config)

	common_config = {}
	if action.requested_by:
		if email := frappe.db.get_value("User", action.requested_by, "email"):
			common_config["letsencrypt"] = {"email": email}
	try:
		common_config["telemetry"] = get_telemetry_configuration(action)
	except Exception:
		action.record_diagnostic(frappe.get_traceback(), "Pilot telemetry configuration failed")
	if common_config:
		metadata["pilot-common-config"] = json.dumps(common_config)

	return metadata


def get_telemetry_configuration(action) -> dict:
	"""The region's Datum and the token the new server writes to it with."""
	endpoint = get_telemetry_base_url(action.region)
	if not endpoint:
		frappe.throw(frappe._("Region {0} has no telemetry host yet.").format(action.region))

	token = mint_datum_token(region_id_of(action.region), action.server_id)

	return {"endpoint": endpoint, "token": token}


class PilotLoginPending(Exception):
	"""Pilot has not accepted Central authentication for a site login yet."""


def fetch_site_login_url(
	gateway_url: str,
	audience_id: str,
	site: str,
	user: str | None = None,
	full_name: str | None = None,
) -> str | None:
	"""Relay a Central-signed site assertion to the bench's login endpoint and return the desk
	URL it mints (a fresh local session) for `user`, or Administrator. A 401 while Pilot finishes
	starting, a rate limit, and a busy or unreachable machine are retryable. A 404 means the bench
	has no site by that name. Other failures return None and are logged so a consistently-failing
	bench or Central is diagnosable."""
	try:
		token = mint_site_login(audience_id, site, user, full_name)
		response = requests.post(
			f"{_gateway_url(gateway_url)}/api/v1/sites/{site}/login",
			headers={"Authorization": f"Bearer {token}"},
			timeout=SITE_LOGIN_TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		# A small machine can time out the login it mints while it is busy. Minting again only
		# starts another session, so these are safe to retry.
		if response.status_code in (401, 429) or response.status_code >= 500:
			raise PilotLoginPending
		if response.status_code == 404:
			return None
		response.raise_for_status()
		payload = response.json()
		url = payload.get("url") if isinstance(payload, dict) else None
	except PilotLoginPending:
		raise
	except (requests.ConnectionError, requests.Timeout):
		raise PilotLoginPending from None
	except Exception:  # minting (signing key / DB / encode) must also fall back, not 500
		frappe.log_error(
			title=f"Site login relay failed: {site}",
			message=f"{gateway_url}: {frappe.get_traceback(with_context=True)}",
		)
		return None
	if not isinstance(url, str) or not url:
		frappe.log_error(
			title=f"Site login relay returned no URL: {site}", message=f"{gateway_url}: {response.text}"
		)
		return None

	return url


def is_site_reachable(url: str) -> bool:
	"""Whether a site answers on its public address.

	The image ships the site already built, so nothing is being provisioned: the question
	is only whether the machine is awake and its route is live."""
	try:
		response = requests.get(
			f"{url}/api/method/ping", timeout=SITE_PING_TIMEOUT_SECONDS, allow_redirects=False
		)
	except requests.RequestException:
		return False

	return response.ok and "pong" in response.text


def rename_admin_domain(server: str, base_url: str | None = None, tls: bool = True) -> dict:
	"""Ask a server's pilot to serve its admin UI at the proxy hostname Central expects.

	`base_url` reaches the pilot when its current admin hostname differs from the expected one.
	Pilot queues the change as a task and returns it."""
	expected = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	payload = {"domain": urlparse(expected).hostname, "tls": tls}

	return _request_pilot("POST", server, base_url or expected, "/api/v1/settings/admin-domain", payload)


def set_site_primary_domain(server: str, site: str, domain: str) -> dict:
	"""Attach the customer's primary domain without moving the site's directory."""
	base_url = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	return _request_pilot(
		"POST",
		server,
		base_url,
		f"/api/v1/sites/{quote(site, safe='')}/domains",
		{"domain": domain, "primary": True},
	)


def rename_site(
	server: str,
	site: str,
	new_name: str,
	keep_old_hostname: bool = True,
	make_primary: bool = False,
	base_url: str | None = None,
) -> dict:
	"""Ask a server's pilot to rename one of its sites. Pilot queues the rename as a task.
	`make_primary` makes the new name the site's `host_name`, so its links use it."""
	base_url = base_url or _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	payload = {"new_name": new_name, "keep_old_hostname": keep_old_hostname, "make_primary": make_primary}

	return _request_pilot(
		"POST", server, base_url, f"/api/v1/sites/{quote(site, safe='')}/actions/rename", payload
	)


def get_site_apps(server: str, site_names: list[str]) -> tuple[str, list[str]]:
	"""The bench's name for the site, and the apps active on it. The bench may know the site by
	any of `site_names`, so each is tried in order."""
	base_url = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	for site in site_names:
		try:
			result = _request_pilot("GET", server, base_url, f"/api/v1/sites/{quote(site, safe='')}/apps")
		except requests.HTTPError as error:
			# Before its rename lands, the bench knows the site only by its image name.
			if error.response is not None and error.response.status_code == 404 and site != site_names[-1]:
				continue
			raise

		return site, [app["name"] for app in result.get("apps", [])]

	frappe.throw(_("The site has no name that its server knows."))


def install_site_app(server: str, site: str, app: str) -> dict:
	"""Ask a server's pilot to install a marketplace app on one of its sites. Pilot queues a task."""
	base_url = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	task = _request_pilot(
		"POST", server, base_url, f"/api/v1/sites/{quote(site, safe='')}/apps", {"app": app}
	)

	# An app that was installed and disabled is enabled at once, with no task.
	return {"site": site, "task_id": task.get("task_id"), "status": task.get("status") or "success"}


def get_site_task(server: str, site: str, task_id: str) -> dict:
	"""Read a task that a server's pilot runs for one of its sites."""
	base_url = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	path = f"/api/v1/sites/{quote(site, safe='')}/tasks/{quote(task_id, safe='')}"
	return _request_pilot("GET", server, base_url, path)


def get_task(server: str, task_id: str) -> dict:
	"""Read a bench task even after its site's directory has moved."""
	base_url = _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	task = _request_pilot("GET", server, base_url, f"/api/v1/tasks/{quote(task_id, safe='')}")
	if not isinstance(task, dict) or task.get("task_id") != task_id:
		raise ValueError("Pilot returned a different task.")
	if task.get("status") not in {"queued", "running", "success", "failed", "killed"}:
		raise ValueError("Pilot returned an invalid task status.")
	return task


def _expected_gateway_url(server) -> str:
	url = frappe.get_cached_doc("Region", server.region).get_vm_gateway_url(server.ipv6_address)
	if not url:
		frappe.throw(frappe._("Server {0} has no proxy hostname.").format(server.name))

	return url


def _request_pilot(method: str, server: str, base_url: str, path: str, payload: dict | None = None) -> dict:
	"""Call a server's pilot as the bench, with a token for its own audience."""
	audience_id = frappe.db.get_value(
		"Pilot Credential", {"server": server, "status": "Active"}, "audience_id"
	)
	if not audience_id:
		frappe.throw(frappe._("Server {0} has no enrolled pilot.").format(server))

	response = requests.request(
		method,
		f"{_gateway_url(base_url)}{path}",
		headers={"Authorization": f"Bearer {mint_bench_login(audience_id)}"},
		json=payload,
		timeout=PILOT_TASK_TIMEOUT_SECONDS,
		allow_redirects=False,
	)
	response.raise_for_status()

	return response.json()


def _gateway_url(value: str) -> str:
	parsed = urlparse(value)
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		frappe.throw(_("The Pilot gateway URL is not valid."))

	return value.rstrip("/")
