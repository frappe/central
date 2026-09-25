from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

import frappe
import requests

from central.api.jwks import jwks_document
from central.api.pilot import get_telemetry_base_url, region_id_of
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.integrations.bucket_provisioning import BucketProvisioning
from central.sso import central_url, jwks_url, mint_bench_login, mint_datum_token, mint_site_login

METRICS_CACHE_TTL_SECONDS = 30
PILOT_TIMEOUT_SECONDS = 3
PILOT_TASK_TIMEOUT_SECONDS = 35
# Minting a session can start a cold Frappe process on the machine. Central waits long
# enough for that process rather than discarding a session the machine creates later.
SITE_LOGIN_TIMEOUT_SECONDS = 120
SITE_PING_TIMEOUT_SECONDS = 4


def get_bootstrap_metadata(action) -> dict[str, str]:
	"""Mint the credential for a Pilot creation and return its guest metadata values."""
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
		"initial_jwks_cache": jwks_document(),
	}

	# Metal caps each metadata value at 1 KiB, so each optional block gets its own key.
	metadata = {"pilot-central": json.dumps(bootstrap)}

	# Object storage and telemetry are optional for a Pilot, so a failure must not block the creation.
	try:
		metadata["pilot-storage"] = json.dumps(BucketProvisioning(action).get_configuration())
	except Exception:
		action.record_diagnostic(frappe.get_traceback(), "Pilot object storage provisioning failed")

	try:
		metadata["pilot-telemetry"] = json.dumps(get_telemetry_configuration(action))
	except Exception:
		action.record_diagnostic(frappe.get_traceback(), "Pilot telemetry configuration failed")

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


class PilotMonitoringClient:
	"""Read a bench's existing, Central-JWKS-authenticated monitoring endpoints."""

	def __init__(self, gateway_url: str, audience_id: str):
		self.gateway_url = _gateway_url(gateway_url)
		self.token = mint_bench_login(audience_id)

	def get_metrics(self) -> dict:
		return self._get("/api/v1/metrics")

	def get_history(self, window: str = "24h") -> dict:
		return self._get("/api/v1/monitor/history", params={"window": window})

	def get_overview(self) -> dict:
		"""Live snapshot + 24h history in parallel — one token, two round-trips overlapped."""
		with ThreadPoolExecutor(max_workers=2) as pool:
			metrics = pool.submit(self.get_metrics)
			history = pool.submit(self.get_history)
			return {"current": metrics.result(), "history": history.result()}

	def _get(self, path: str, params: dict | None = None) -> dict:
		try:
			response = requests.get(
				f"{self.gateway_url}{path}",
				headers={"Authorization": f"Bearer {self.token}"},
				params=params,
				timeout=PILOT_TIMEOUT_SECONDS,
				allow_redirects=False,
			)
			response.raise_for_status()
			payload = response.json()
		except (requests.RequestException, ValueError) as exc:
			raise PilotMonitoringError from exc
		if not isinstance(payload, dict):
			raise PilotMonitoringError
		return payload


def fetch_site_login_url(gateway_url: str, audience_id: str, site: str) -> str | None:
	"""Relay a Central-signed site assertion to the bench's login endpoint and return the desk
	URL it mints (a fresh local session). A 401 is retryable while Pilot finishes starting. Other
	failures return None and are logged so a consistently-failing bench or Central is diagnosable."""
	try:
		response = requests.post(
			f"{_gateway_url(gateway_url)}/api/v1/sites/{site}/login",
			headers={"Authorization": f"Bearer {mint_site_login(audience_id, site)}"},
			timeout=SITE_LOGIN_TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		if response.status_code == 401:
			raise PilotLoginPending
		response.raise_for_status()
		payload = response.json()
		url = payload.get("url") if isinstance(payload, dict) else None
	except PilotLoginPending:
		raise
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
	return _post_to_pilot(server, base_url or expected, "/api/v1/settings/admin-domain", payload)


def rename_site(
	server: str, site: str, new_name: str, keep_old_hostname: bool = True, base_url: str | None = None
) -> dict:
	"""Ask a server's pilot to rename one of its sites. Pilot queues the rename as a task."""
	base_url = base_url or _expected_gateway_url(frappe.get_doc("Virtual Machine", server))
	payload = {"new_name": new_name, "keep_old_hostname": keep_old_hostname}
	return _post_to_pilot(server, base_url, f"/api/v1/sites/{quote(site, safe='')}/actions/rename", payload)


def _expected_gateway_url(server) -> str:
	url = frappe.get_cached_doc("Region", server.region).get_vm_gateway_url(server.ipv6_address)
	if not url:
		frappe.throw(frappe._("Server {0} has no proxy hostname.").format(server.name))
	return url


def _post_to_pilot(server: str, base_url: str, path: str, payload: dict) -> dict:
	audience_id = frappe.db.get_value(
		"Pilot Credential", {"server": server, "status": "Active"}, "audience_id"
	)
	if not audience_id:
		frappe.throw(frappe._("Server {0} has no enrolled pilot.").format(server))

	response = requests.post(
		f"{_gateway_url(base_url)}{path}",
		headers={"Authorization": f"Bearer {mint_bench_login(audience_id)}"},
		json=payload,
		timeout=PILOT_TASK_TIMEOUT_SECONDS,
		allow_redirects=False,
	)
	response.raise_for_status()
	return response.json()


class PilotMonitoringError(Exception):
	"""Pilot is unavailable or returned an unexpected monitoring response."""


def get_cached_monitoring(resource_id: str, gateway_url: str, audience_id: str) -> dict:
	"""Return one server's live snapshot and 24-hour history from a short Central cache."""
	key = f"pilot:monitoring:{resource_id}"
	if cached := frappe.cache.get_value(key):
		return cached

	try:
		payload = PilotMonitoringClient(gateway_url, audience_id).get_overview()
		monitoring = {"available": True, **payload}
	except PilotMonitoringError:
		frappe.log_error(title=f"Pilot monitoring unavailable: {resource_id}")
		monitoring = {"available": False}

	frappe.cache.set_value(key, monitoring, expires_in_sec=METRICS_CACHE_TTL_SECONDS)
	return monitoring


def _gateway_url(value: str) -> str:
	parsed = urlparse(value)
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		raise PilotMonitoringError
	return value.rstrip("/")
