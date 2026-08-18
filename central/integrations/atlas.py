from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.frappeclient import FrappeClient, FrappeException
from frappe.utils.password import get_decrypted_password

from central.central.doctype.asset.asset import Asset
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.central.doctype.resource_action.resource_action import ResourceAction
from central.central.doctype.site.site import Site
from central.errors import throw_action_error
from central.host_task import run_host_task

# Central's integration with the regional Atlas clusters (Edge B), all in one place:
#   - outbound: AtlasClient calls Atlas over Frappe's FrappeClient (token auth from
#     the per-instance API key/secret on the Atlas Instance record).
#   - inbound: the Asset mirror is kept fresh two ways — Atlas pushes lifecycle
#     events to ingest_event (low latency), and reconcile pulls the authoritative
#     list to correct drift. The Asset controller is the mirror's sole writer; this
#     module only decides when and from where.


# --- outbound: Central → Atlas ----------------------------------------------


# Hard timeout (seconds) for the capacity reads on the create-server / resize menu path.
# Short on purpose: these run on every menu render and fail soft (a timeout just shows the
# full menu), so a degraded Atlas must not hold a worker longer than a page can wait.
CAPACITY_TIMEOUT = 3


class AtlasError(frappe.ValidationError):
	pass


class AtlasResourceGone(AtlasError):
	"""Atlas has no such resource (HTTP 404). For terminate this means already gone —
	the caller can treat it as idempotent success; for other actions it's a clean error."""


# Generous bound for a synchronous lifecycle call (Atlas runs terminate/start on the host
# in-request); long enough for a real op, short enough that a dead region can't pin a worker.
LIFECYCLE_TIMEOUT = 120


# The last line of a Python traceback is always "<dotted.ExcType>: <message>". That is
# the only part of a remote failure worth showing a caller, so it is what we lift out of
# the traceback FrappeClient hands us (see `_post`).
_REMOTE_EXC_LINE = re.compile(r"^(?P<type>[\w.]+):\s*(?P<message>.+)$")


def _remote_error_message(exception: Exception) -> str | None:
	"""Pull Atlas's own error sentence out of a FrappeClient failure, or None.

	`FrappeClient.post_process` raises FrappeException whose single argument is
	"FrappeClient Request Failed\\n\\n" followed by Atlas's ENTIRE remote traceback as
	one string. The actionable sentence Atlas raised — "Capacity is being freed by
	migrating small VMs — retry shortly.", "Image X is not present on any active
	server yet", "No capacity available — contact your operator." — is the last line.
	Everything above it is Atlas's internal frames, which are useless to the caller and
	should not be rendered into a tenant's browser.

	Returns None when the payload isn't a remote traceback (a connection error, say),
	so the caller can fall back to a generic message rather than print something wrong.
	"""
	text = str(exception or "").strip()
	if not text:
		return None
	for line in reversed(text.splitlines()):
		match = _REMOTE_EXC_LINE.match(line.strip())
		if match:
			return match.group("message").strip() or None
	return None


def _server_message(response: requests.Response) -> str | None:
	"""Atlas's own error sentence from a failed response's `_server_messages`, or None."""
	try:
		raw = response.json().get("_server_messages")
		if not raw:
			return None
		first = frappe.parse_json(frappe.parse_json(raw)[0])
		return frappe.utils.strip_html_tags(first.get("message") or "") or None
	except Exception:
		return None


def get_atlas_instance(region: str):
	"""Resolve a region (= cluster) to its `Atlas Instance`, or raise."""
	name = frappe.db.get_value("Atlas Instance", {"region": region})
	if not name:
		frappe.throw(_("No Atlas registered for region '{0}'.").format(region), AtlasError)
	return frappe.get_doc("Atlas Instance", name)


class AtlasClient:
	"""A FrappeClient bound to one regional Atlas, built from its Atlas Instance."""

	def __init__(self, instance):
		self.instance = instance

	@classmethod
	def for_region(cls, region: str) -> "AtlasClient":
		return cls(get_atlas_instance(region))

	def client(self) -> FrappeClient:
		"""The data-path client (vm_action / create_vm / central_vms / reconcile).
		Central→Atlas authenticates with the Atlas ADMIN token throughout
		(spec/21-tunnel.md § Credentials); the target is the tunnel_url over wg0 once the
		tunnel is Active, and the public base_url only during bootstrap."""
		if self.instance.status == "Disabled":
			frappe.throw(_("Atlas '{0}' is disabled.").format(self.instance.region), AtlasError)
		return self._admin_client(self._data_url())

	def _data_url(self) -> str:
		if self.instance.tunnel_status == "Active" and self.instance.tunnel_url:
			return self.instance.tunnel_url
		return self.instance.base_url

	def _post(self, method: str, params: dict, *, action: str) -> Any:
		"""POST to Atlas, translating a remote failure into Atlas's own error.

		Every tenant-triggered write goes through here. Without it, an Atlas-side
		`frappe.throw` (region full, image not on any host, size rejected) surfaces to
		the tenant as a bare `FrappeException` wrapping Atlas's whole traceback: the one
		sentence that tells them what to do is buried under Atlas internals they should
		never see. We re-raise it as `AtlasError` carrying just that sentence, and keep
		the full traceback in the Error Log for operators.

		`action` names the operation for the fallback message, used when the failure
		isn't a remote traceback at all (Atlas unreachable, TLS error, timeout).
		"""
		try:
			return self.client().post_api(method, params=params)
		except FrappeException as exception:
			frappe.log_error(
				title=f"Atlas '{self.instance.region}': {action} failed",
				message=str(exception),
			)
			sentence = _remote_error_message(exception)

			# The region's own sentence is the best message a user can get; without one the
			# failure is a network/timeout — transient, and safe to retry.
			if sentence:
				throw_action_error("ATLAS_REJECTED", exc=AtlasError, message=sentence, action=action)
			throw_action_error(
				"REGION_UNAVAILABLE", exc=AtlasError, action=action, region=self.instance.region
			)

	def _run_doc_method(self, dt: str, dn: str, method: str, args: dict | None, *, action: str) -> Any:
		"""Invoke a whitelisted controller method on Atlas, reading the real HTTP status so a
		missing doc (404) is told apart from an unreachable region — unlike FrappeClient, which
		collapses both into an opaque failure. Returns the method's result; raises
		AtlasResourceGone on 404 (for terminate that means already gone), AtlasError otherwise."""
		if self.instance.status == "Disabled":
			frappe.throw(_("Atlas '{0}' is disabled.").format(self.instance.region), AtlasError)
		if not self.instance.api_key:
			frappe.throw(_("Atlas '{0}' has no admin API key.").format(self.instance.region), AtlasError)

		url = self._data_url().rstrip("/") + "/api/method/run_doc_method"
		params = {"dt": dt, "dn": dn, "method": method}
		if args:
			params["args"] = json.dumps(args)
		secret = self.instance.get_password("api_secret")

		try:
			response = requests.post(
				url,
				headers={"Authorization": f"token {self.instance.api_key}:{secret}"},
				data=params,
				timeout=LIFECYCLE_TIMEOUT,
			)
		except requests.RequestException:
			throw_action_error(
				"REGION_UNAVAILABLE", exc=AtlasError, action=action, region=self.instance.region
			)

		if response.ok:
			return response.json().get("message")

		# Keep the full body for operators; hand the caller Atlas's own sentence.
		frappe.log_error(
			title=f"Atlas '{self.instance.region}': {action} failed", message=response.text[:2000]
		)
		if response.status_code == 404:
			throw_action_error("RESOURCE_GONE", exc=AtlasResourceGone, action=action)
		sentence = _server_message(response)
		if sentence:
			throw_action_error("ATLAS_REJECTED", exc=AtlasError, message=sentence, action=action)
		throw_action_error("REGION_UNAVAILABLE", exc=AtlasError, action=action, region=self.instance.region)

	def ping(self) -> dict:
		"""Reachability + auth check against the frappe ping endpoint."""
		return self.client().get_api("ping")

	def vm_action(self, name: str, method: str, *, correlation_id: str | None = None) -> str:
		"""Invoke a Virtual Machine lifecycle method (start/stop/terminate) as the operator;
		return the resulting Task name. `correlation_id` rides back on the resulting event so
		Central can match it to the Resource Action that requested it."""
		args = {"correlation_id": correlation_id} if correlation_id else None

		return self._run_doc_method("Virtual Machine", name, method, args, action=f"{method} this server")

	def resize_vm(
		self,
		name: str,
		*,
		vcpus: int,
		memory_megabytes: int,
		disk_gigabytes: int,
	) -> str:
		"""Resize a VM's compute shape (the resize() doc method takes kwargs, unlike
		the arg-less lifecycle verbs, so it goes through run_doc_method's `args`).
		Atlas refuses a resize on a running VM — the caller gates on Stopped first.
		Returns the on-host resize Task name."""
		return self._post(
			"run_doc_method",
			{
				"dt": "Virtual Machine",
				"dn": name,
				"method": "resize",
				"args": json.dumps(
					{
						"vcpus": int(vcpus),
						"memory_megabytes": int(memory_megabytes),
						"disk_gigabytes": int(disk_gigabytes),
					}
				),
			},
			action="resize this server",
		)

	def create_vm(
		self,
		*,
		team: str,
		title: str,
		vcpus: int,
		memory_megabytes: int,
		disk_gigabytes: int,
		cpu_max_cores: float | None = None,
		frappe_version: str | None = None,
		correlation_id: str | None = None,
	) -> dict:
		"""Provision a VM on this Atlas for a Central team (the operator write).
		Returns the new VM in the Asset-mirror shape so the caller can upsert it.

		For a bench VM, `title` doubles as the subdomain — Atlas fronts it at
		`title.<region domain>` and reports that back as gateway_url. The one-click
		login URL is minted after boot, so it (and its expiry) arrive later on the
		vm.status_changed event, not in this reply."""
		params: dict = {
			"team": team,
			"title": title,
			"vcpus": vcpus,
			"memory_megabytes": memory_megabytes,
			"disk_gigabytes": disk_gigabytes,
		}
		if cpu_max_cores:
			params["cpu_max_cores"] = cpu_max_cores
		if frappe_version:
			params["frappe_version"] = frappe_version
		if correlation_id:
			params["correlation_id"] = correlation_id
		# Same enrollment carriage as create_site: mint the single-use bootstrap token and
		# credential id so the bench can run `bench admin enroll` on first boot. Without it
		# a server provisions fine but never enrols, and Open Console refuses it with
		# "This VM's pilot hasn't enrolled yet" (central/api/sso.py). Sites had this;
		# servers did not, which is why only servers were unopenable.
		params.update(self._pilot_credential(team))
		# Commit before the Atlas call for the same durability reason create_site has:
		# minting lazily generates Central's signing key, and a rollback of the enclosing
		# request must not discard a key the booting bench already holds a token signed by.
		frappe.db.commit()
		return self._post("atlas.atlas.api.provision.create_vm", params, action="create this server")

	def capacity(self) -> dict:
		"""Ask this region what it can seat right now: `{available, unmeasured, largest_vm}`.

		Central speaks in resources, never hosts — placement is Atlas's concern
		(spec/16-central.md). `largest_vm` is the biggest single VM shape placeable now
		(`{vcpus, memory_megabytes, disk_gigabytes}`, or null when no Active host exists);
		the create-server menu hides plans that don't fit it. Advisory only — placement's
		create-time gate is authoritative, since capacity can move between this read and
		the create."""
		return self._get_bounded("atlas.atlas.api.provision.capacity")

	def resize_capacity(self, vm: str) -> dict:
		"""The largest shape `vm` can resize to on its current host: `{available,
		unmeasured, largest_vm}`. The in-place twin of `capacity()` — the ceiling includes
		the VM's own footprint (a resize frees it before re-reserving), so the VM can always
		keep its size or shrink. The create-server menu caps the resize slider to this so an
		oversized resize can't be requested. Advisory — the host resize path is authoritative."""
		return self._get_bounded("atlas.atlas.api.provision.resize_capacity", {"vm": vm})

	def _get_bounded(self, method: str, params: dict | None = None, timeout: int = CAPACITY_TIMEOUT) -> dict:
		"""Admin-auth GET against the data path with a HARD timeout — the bounded twin of
		`client().get_api`. The capacity reads run on every create-server / resize menu
		render, and FrappeClient (like requests) has no default timeout, so a silently-hung
		Atlas (slow net, overloaded host) would otherwise pin a Gunicorn worker on the OS
		TCP timeout and stall every user in that region. A timeout raises here and the
		caller's fail-soft path treats it as 'don't gate' (show the full menu). Returns the
		endpoint's `message` payload."""
		if self.instance.status == "Disabled":
			frappe.throw(_("Atlas '{0}' is disabled.").format(self.instance.region), AtlasError)
		if not self.instance.api_key:
			frappe.throw(_("Atlas '{0}' has no admin API key.").format(self.instance.region), AtlasError)
		url = self._data_url().rstrip("/") + "/api/method/" + method
		secret = self.instance.get_password("api_secret")
		response = requests.get(
			url,
			headers={"Authorization": f"token {self.instance.api_key}:{secret}"},
			params=params or {},
			timeout=timeout,
		)
		response.raise_for_status()
		return response.json().get("message", {})

	def central_vms(self, team: str | None = None) -> list[dict]:
		"""Tenant-tagged VMs on this Atlas for the mirror reconcile (optionally one
		team). One dict per VM in the Asset-mirror shape — including the bench login
		handoff (gateway_url + login_url/expiry, the latter only once Running) and the
		provisioned frappe_version."""
		params = {"team": team} if team else None
		return self.client().get_api("atlas.atlas.api.inventory.tenant_vms", params)

	def available_frappe_versions(self) -> list[str]:
		"""The Frappe versions this region can provision — the tokens of its active
		bench images. Bounded/fail-soft like the capacity reads (it feeds the same
		new-server menu); the caller falls back to a static set if it raises."""
		return self._get_bounded("atlas.atlas.api.inventory.available_frappe_versions") or []

	# --- admin-auth path: the registration handshake (TUNNEL.md) -------------
	# Central→Atlas authenticates with the Atlas ADMIN creds (api_key/api_secret on the
	# Atlas Instance) for everything: provision_tunnel over the public base_url; the verify
	# ping + confirm_tunnel over the tunnel_url, so reaching them is itself the proof that
	# wg0 works before the public side is locked for good.

	def _admin_client(self, base_url: str) -> FrappeClient:
		if not self.instance.api_key:
			frappe.throw(_("Atlas '{0}' has no admin API key.").format(self.instance.region), AtlasError)
		return FrappeClient(
			base_url,
			api_key=self.instance.api_key,
			api_secret=self.instance.get_password("api_secret"),
		)

	def admin_ping(self, base_url: str) -> dict:
		"""Ping Atlas's frappe endpoint with the admin token at `base_url` — the public
		bootstrap URL during step 1, the tunnel_url during the over-the-tunnel verify."""
		return self._admin_client(base_url).get_api("ping")

	def provision_tunnel(self, base_url: str, payload: dict) -> dict:
		"""Atlas inbound provision_tunnel over the public base_url (admin auth): Atlas
		brings up wg0, locks its public firewall with the auto-revert armed, stores the
		pushed creds, and returns { wg_public_key, listen_port, tunnel_ip }."""
		return self._admin_client(base_url).post_api(
			"atlas.atlas.api.central_link.provision_tunnel", params=payload
		)

	def link_local(self, base_url: str, payload: dict) -> dict:
		"""Local-dev registration over the public base_url (admin auth): push the
		service-user creds with skip_tunnel set, so Atlas stores them and enables event
		reporting but brings up no wg0 and locks no firewall. Reuses provision_tunnel — the
		flag branches it before any host script runs."""
		return self._admin_client(base_url).post_api(
			"atlas.atlas.api.central_link.provision_tunnel", params={**payload, "skip_tunnel": 1}
		)

	def confirm_tunnel(self, tunnel_url: str) -> dict:
		"""Atlas inbound confirm_tunnel OVER the tunnel (admin auth): Atlas persists the
		lockdown and cancels its auto-revert. Returns { tunnel_status }."""
		return self._admin_client(tunnel_url).post_api(
			"atlas.atlas.api.central_link.confirm_tunnel", params={}
		)

	def deprovision_tunnel(self, base_url: str, timeout: int = 15) -> dict:
		"""Atlas inbound deprovision_tunnel (admin auth): Atlas reverts its firewall +
		drops wg0 + clears its tunnel fields. Called over the tunnel while Active, so the
		teardown drops wg0 and the response usually never returns. FrappeClient has no
		timeout, and a torn tunnel drops packets silently (no RST) — so use a direct
		request with a bounded timeout; the host work commits server-side regardless and
		the caller (remove_tunnel) tolerates the timeout and re-verifies over base_url."""
		if not self.instance.api_key:
			frappe.throw(_("Atlas '{0}' has no admin API key.").format(self.instance.region), AtlasError)
		url = base_url.rstrip("/") + "/api/method/atlas.atlas.api.central_link.deprovision_tunnel"
		secret = self.instance.get_password("api_secret")
		response = requests.post(
			url,
			headers={"Authorization": f"token {self.instance.api_key}:{secret}"},
			timeout=timeout,
		)
		response.raise_for_status()
		return response.json().get("message", {})

	def create_site(
		self,
		*,
		team: str,
		subdomain: str,
		region: str | None = None,
		correlation_id: str | None = None,
	) -> dict:
		"""
		Provision a self-serve site on this Atlas for a Central team (the operator
		write). Returns the site in the Site-mirror shape so the caller can upsert it.
		`correlation_id` rides back on the site.* events so Central can match the outcome.
		"""

		params: dict = {"team": team, "subdomain": subdomain}

		if region:
			params["region"] = region
		if correlation_id:
			params["correlation_id"] = correlation_id
		params.update(self._pilot_credential(team))

		# Durability: minting the bootstrap token lazily generates Central's signing key on
		# first use. Commit BEFORE the Atlas call so a rollback of the enclosing request
		# can't discard a freshly-generated key while the bench boots with a token signed by
		# it. The bootstrap token itself is stateless (a signed JWT, no DB row) and the
		# long-lived credential is created only later at enrollment, so nothing else here
		# needs committing; an unused token after a failed Atlas call is harmless.
		frappe.db.commit()
		site = self._post("atlas.atlas.api.site.create_site", params, action="create this site")
		# Central minted this credential, so carry it onto the mirror as the site→pilot key.
		site["pilot_credential_id"] = params["pilot_credential_id"]
		return site

	def _pilot_credential(self, team: str) -> dict:
		"""
		Mint a single-use enrollment (bootstrap) token and hand Atlas the token + callback
		URL to seed on the bench (bench.toml). On first boot the pilot exchanges it for its
		long-lived credential (`central.api.pilot.enroll`) — the durable secret is never
		injected during provisioning, only a short-lived, single-use one. Atlas binds
		pilot_credential_id to the pilot and echoes it back to join events, which links the
		enrolled credential to its VM.
		"""
		from central.sso import central_url, mint_bootstrap_token

		pilot_credential_id = f"pcred-{frappe.generate_hash(length=16)}"
		# Reserve the row now (no token) so the vm.* events can bind its Asset link even if
		# they arrive before the pilot boots and enrols. The token is issued only at enroll.
		PilotCredential.reserve(
			team=team, pilot_credential_id=pilot_credential_id, audience_id=pilot_credential_id
		)

		return {
			"pilot_credential_id": pilot_credential_id,
			"central_endpoint": central_url(),
			"bootstrap_token": mint_bootstrap_token(team=team, pilot_credential_id=pilot_credential_id),
		}

	def get_site(self, name: str) -> dict:
		"""
		Poll one site's current state — the self-heal fallback to the site.* events.
		Returns the mirror shape, with url + the one-click login_url (and its expiry)
		once the site is Running.
		"""

		return self.client().post_api("atlas.atlas.api.site.get_site", params={"name": name})

	def regenerate_site_login(self, name: str) -> dict:
		"""Re-mint a serving site's one-click login URL and return the fresh Site-mirror
		shape (url + login_url + login_url_expires_at). Central calls this when a tenant
		clicks their login link after the stored URL's 24h session has expired — the URL
		is short-lived by design, so it is re-signed on demand. The Atlas Site controller
		re-mints in the guest, re-stamps, and returns the mirror."""
		return self._post(
			"run_doc_method",
			{"dt": "Site", "dn": name, "method": "regenerate_login_url"},
			action="refresh this site's login link",
		)

	def terminate_site(self, name: str, *, correlation_id: str | None = None) -> dict:
		"""Tear down a self-serve site and its 1:1 backing VM. The Atlas Site controller
		terminates the guest + VM; the site.* events flip the mirror to Terminated. Raises
		AtlasResourceGone if the site is already gone on Atlas, so terminate stays idempotent."""
		args = {"correlation_id": correlation_id} if correlation_id else None

		return self._run_doc_method("Site", name, "terminate", args, action="terminate this site")

	def check_subdomain(self, subdomain: str, region: str | None = None) -> dict:
		"""Best-effort availability pre-check: {available, reason, fqdn, domain}."""
		params = {"subdomain": subdomain}

		if region:
			params["region"] = region

		return self.client().get_api("atlas.atlas.api.site.check_subdomain", params)


# --- inbound push: webhook events (central.api.atlas.event delegates here) ---


def ingest_event(
	cluster: str,
	event_type: str,
	payload: dict,
	occurred_at,
	event_id: str | None = None,
	raw_body: bytes | None = None,
	signature: str | None = None,
	signature_timestamp: str | None = None,
) -> dict:
	"""Persist the event under the caller-verified `cluster`, then queue the mirror write
	for the types Central mirrors. raw_body/signature/signature_timestamp are kept verbatim
	so the row stays self-verifying; raw_payload is reserialized and never verifies."""

	# A validly-signed but malformed event (no id or type) can't be stored or deduped —
	# ack it so Atlas stops retrying, as before. Real events always carry both.
	if not (event_id and event_type):
		return {"ok": True, "queued": False}

	# A redelivery carries the same event_id, so skip anything we've already stored.
	# The unique constraint on event_id is the backstop against a concurrent double
	# delivery slipping past this check.
	if frappe.db.exists("Atlas Event", {"event_id": event_id}):
		return {"ok": True, "queued": False}

	# Record every authenticated event. A type Central doesn't mirror yet lands as Ignored
	# rather than vanishing — so the audit trail is complete and a handler added later has
	# history to replay. after_insert queues the mirror write only for a Received row.
	handled = event_type in _EVENT_HANDLERS

	frappe.get_doc(
		{
			"doctype": "Atlas Event",
			"cluster": cluster,
			"event_id": event_id,
			"event_type": event_type,
			"occurred_at": occurred_at,
			"signature": signature,
			"signature_timestamp": signature_timestamp,
			"raw_body": raw_body.decode() if isinstance(raw_body, bytes) else raw_body,
			"raw_payload": frappe.as_json(payload or {}),
			"status": "Received" if handled else "Ignored",
		}
	).insert(ignore_permissions=True)

	return {"ok": True, "queued": handled}


def apply_event(event_name: str) -> None:
	"""Background job: apply one stored Atlas event to the Asset mirror."""
	event = frappe.get_doc("Atlas Event", event_name)
	payload = frappe.parse_json(event.raw_payload) if event.raw_payload else {}

	try:
		_EVENT_HANDLERS[event.event_type](event.cluster, payload, event.occurred_at)
	except Exception as exception:
		# Commit the failure stamp before re-raising: the job runner rolls back on the
		# way out, which would otherwise discard it and leave the row stuck at Received.
		frappe.db.set_value(
			"Atlas Event",
			event_name,
			{"status": "Failed", "error": str(exception)},
			update_modified=False,
		)
		frappe.db.commit()
		raise

	event.status = "Processed"
	event.processed_at = frappe.utils.now_datetime()
	event.save(ignore_permissions=True)


def verify_atlas_webhook(func: Callable) -> Callable:
	"""Authenticates the HMAC over the raw body before the handler runs, stashing the
	verified context on frappe.local. functools.wraps is required — Frappe maps request
	args off the wrapped signature."""

	@functools.wraps(func)
	def wrapper(*args, **kwargs):
		frappe.local.atlas_webhook = _authenticate_atlas_webhook(frappe.request.get_data())
		return func(*args, **kwargs)

	return wrapper


def _authenticate_atlas_webhook(raw_body: bytes) -> frappe._dict:
	"""Authenticate an inbound webhook and return its verified context. X-Atlas-Region only
	selects which secret to check, never trusted on its own; every failure throws the same
	generic message."""
	region = frappe.get_request_header("X-Atlas-Region")
	timestamp = frappe.get_request_header("X-Atlas-Timestamp")
	signature = frappe.get_request_header("X-Atlas-Signature")
	if not (region and timestamp and signature):
		_reject_signature("missing signature headers")

	instance = frappe.db.get_value("Atlas Instance", {"region": region, "status": ["!=", "Disabled"]})
	if not instance:
		_reject_signature(f"unknown or disabled region '{region}'")

	secret = get_decrypted_password("Atlas Instance", instance, "webhook_secret", raise_exception=False)
	if not secret:
		_reject_signature(f"no webhook secret for region '{region}'")

	if not signature_matches(secret, timestamp, raw_body, signature):
		_reject_signature(f"signature mismatch for region '{region}'")

	return frappe._dict(cluster=instance, raw=raw_body, signature=signature, timestamp=timestamp)


def signature_matches(secret: str, timestamp, raw_body: bytes, signature: str) -> bool:
	"""Constant-time check. Bytes not str — compare_digest raises TypeError on non-ASCII."""
	expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected.encode(), signature.encode())


def _reject_signature(reason: str):
	"""Log the specific reason to the Error Log for operators — repeated rejections mean
	secret drift or a forged caller, invisible before this — but throw one uniform 403 so a
	caller can't probe which check failed."""
	frappe.log_error(title="Rejected inbound Atlas webhook", message=reason)

	# Uniform 403. Don't set http_status_code — Frappe's exception handler overrides it.
	frappe.throw(_("Invalid webhook signature."), frappe.PermissionError)


def _on_vm(cluster: str, payload: dict, occurred_at) -> None:
	Asset.mirror_vm(cluster, payload, occurred_at=occurred_at)
	# Once Atlas echoes the pilot_credential_id, bind the credential to its VM.
	PilotCredential.link_asset(payload.get("pilot_credential_id"), payload.get("name"))
	# Confirm the action that asked for this change (create/start/stop/restart) against its outcome.
	ResourceAction.record_mirror_status(payload.get("correlation_id"), payload.get("status"))


def _on_vm_deleted(cluster: str, payload: dict, occurred_at) -> None:
	resource_id = payload.get("name")
	if resource_id:
		# mark_terminated locks + applies LWW; a stale delete must not overwrite a
		# newer status_changed that already landed on the mirror.
		Asset.mark_terminated(resource_id, last_event_at=occurred_at)
	# The pilot dies with its VM — kill its Central credential so a leaked token is inert.
	PilotCredential.revoke_by_id(payload.get("pilot_credential_id"))
	# A delete is the terminal outcome of a terminate action.
	ResourceAction.record_mirror_status(payload.get("correlation_id"), "Terminated")


def _on_site(cluster: str, payload: dict, occurred_at) -> None:
	Site.mirror_site(cluster, payload, occurred_at=occurred_at)
	# Confirm the site action (create/terminate) this status carries the outcome of.
	ResourceAction.record_mirror_status(payload.get("correlation_id"), payload.get("status"))


_EVENT_HANDLERS = {
	"vm.created": _on_vm,
	"vm.status_changed": _on_vm,
	"vm.resized": _on_vm,
	"vm.deleted": _on_vm_deleted,
	"site.created": _on_site,
	"site.status_changed": _on_site,
}


# --- inbound pull: reconcile (periodic + manual backstop) -------------------


def reconcile(team: str | None = None) -> dict:
	"""Reconcile the Asset mirror against every Active Atlas — the periodic backstop
	to the event push (and the scheduler entry point). Fail-soft: an unreachable
	Atlas is reported in `stale`, its last-known mirror left intact."""
	synced, stale = [], []
	for name in frappe.get_all("Atlas Instance", {"status": "Active"}, pluck="name"):
		try:
			reconcile_atlas(frappe.get_doc("Atlas Instance", name), team)
			synced.append(name)
		except Exception:
			frappe.log_error(title=f"Atlas reconcile failed: {name}")
			_notify_cluster_degraded(name)
			stale.append(name)
	return {"synced": synced, "stale": stale}


def _notify_cluster_degraded(cluster: str) -> None:
	"""Warn teams running in an unreachable cluster that their console view may be
	stale. Fans out one Server-category warning per affected team, deduped to a single
	open notice per (team, cluster) so a flapping/slow Atlas doesn't spam the feed."""
	from central.notification import engine

	teams = frappe.get_all(
		"Asset",
		filters={"cluster": cluster, "status": ["!=", "Terminated"]},
		pluck="team",
		distinct=True,
	)
	for team in {t for t in teams if t}:
		engine.ensure_event_type(
			"cluster_degraded",
			category="Server",
			severity="Warning",
			required_cap="server:view",
			in_app_title="Region unavailable: {{ reference_name }}",
			in_app_body="Region {{ reference_name }}: {{ message }}",
			action_label="View servers",
			action_route="/servers",
		)
		engine.dispatch(
			team,
			"cluster_degraded",
			message=f"Central couldn't reach {cluster} on the last sync. Your servers keep running; "
			"their status in the console may be delayed until the region recovers.",
			reference_doctype="Atlas Instance",
			reference_name=cluster,
		)


def reconcile_atlas(instance, team: str | None = None) -> int:
	"""Pull the authoritative VM list from one Atlas and sync the mirror: upsert
	each, then mark vanished ones Terminated. Optionally scope to one team."""
	now = frappe.utils.now_datetime()
	vms = AtlasClient(instance).central_vms(team)
	seen = {vm.get("name") for vm in vms}
	for vm in vms:
		Asset.mirror_vm(instance.name, vm, synced_at=now)
	gone = {"cluster": instance.name, "status": ["!=", "Terminated"]}
	if team:
		gone["team"] = team
	for resource_id in frappe.get_all("Asset", filters=gone, pluck="name"):
		if resource_id not in seen:
			Asset.mark_terminated(resource_id, last_synced_at=now)
	return len(vms)


# --- Register orchestration: Central drives the tunnel handshake -------------
# central/spec/TUNNEL.md § Register Atlas. The operator supplies admin creds + base_url
# + region and clicks Register; this runs the 8-step handshake with a lockout-safe
# rollback. Atlas's own armed auto-revert restores its public firewall if confirm never
# arrives, so a failure here can't leave the Atlas dark — we undo only the Central-side
# half (the half-added hub peer + the scoped service user).

SERVICE_ROLE = "Atlas Service"


class TunnelRegistrationError(AtlasError):
	pass


def register_atlas(instance) -> dict:
	"""Run the full Central-driven registration handshake for one Atlas Instance.

	1. ping over the public base_url (admin auth); 2. ensure the hub is up + allocate
	tunnel_ip; 3. mint the scoped service user; 4. provision_tunnel over
	base_url; 5. hub-peer-add on the hub; 6. ping at tunnel_ip over wg0; 7.
	confirm_tunnel over the tunnel; 8. tunnel_status=Active. Any failure before confirm
	rolls back the Central-side half and raises TunnelRegistrationError; the instance
	stays whatever it was (Atlas's auto-revert reopens its own firewall)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if not (instance.api_key and instance.get_password("api_secret", raise_exception=False)):
		frappe.throw(_("Set the Atlas admin API key and secret before registering."), TunnelRegistrationError)

	if instance.skip_tunnel:
		return _register_local(instance)

	settings = frappe.get_single("Central Tunnel Settings")
	if settings.hub_status != "Active":
		frappe.throw(_("Initialize the hub before registering an Atlas."), TunnelRegistrationError)

	# Re-registering an already-registered (Inactive) instance just re-tunnels it: reuse
	# its identity, and on failure fall back to Inactive rather than tearing the identity
	# down. A first registration that fails rolls all the way back to Unregistered.
	was_registered = bool(instance.service_user)
	client = AtlasClient(instance)

	# 1. Prove the public bootstrap path + admin creds before changing anything.
	client.admin_ping(instance.base_url)

	# 2-3. Allocate the tunnel address and mint the scoped service identity. Reuse an
	# existing allocation/user on re-tunnel so the Atlas keeps a stable address.
	tunnel_ip = instance.tunnel_ip or settings.allocate_tunnel_ip()
	service_user = _ensure_service_user(instance)
	api_key, api_secret = _rotate_service_credentials(service_user)
	webhook_secret = _rotate_webhook_secret(instance)

	peer_added = False
	try:
		# 4. Atlas brings up wg0 + arms its firewall, returns its public key + port.
		provision = client.provision_tunnel(
			instance.base_url,
			{
				"hub_public_key": settings.hub_public_key,
				"hub_endpoint": settings.hub_endpoint,
				"tunnel_ip": tunnel_ip,
				"tunnel_cidr": settings.tunnel_cidr,
				"central_url": frappe.utils.get_url(),
				"service_api_key": api_key,
				"service_api_secret": api_secret,
				"service_webhook_secret": webhook_secret,
			},
		)
		peer_public_key = provision["wg_public_key"]
		peer_endpoint = _peer_endpoint(instance.base_url, provision["listen_port"])

		instance.tunnel_ip = tunnel_ip
		instance.peer_public_key = peer_public_key
		instance.peer_endpoint = peer_endpoint
		instance.service_user = service_user
		instance.tunnel_status = "Provisioning"
		instance.save(ignore_permissions=True)  # validate() derives tunnel_url from tunnel_ip

		# 5. Add the spoke as a hub peer (the hub dials the Atlas's public endpoint).
		run_host_task(
			script="hub-peer-add.py",
			variables={
				"PEER_PUBLIC_KEY": peer_public_key,
				"ALLOWED_IPS": f"{tunnel_ip}/32",
				"ENDPOINT": peer_endpoint,
			},
		)
		peer_added = True

		# 6. Verify reachability over wg0, then 7. confirm over the tunnel. The hub only
		# just added the peer, so the first packet triggers the WireGuard handshake and
		# can race it — retry the verify ping until the tunnel settles.
		_verify_over_tunnel(client, instance.tunnel_url)
		client.confirm_tunnel(instance.tunnel_url)

		# 8. The lockdown is now proven safe to keep.
		instance.tunnel_status = "Active"
		instance.save(ignore_permissions=True)
	except Exception as exception:
		_rollback(instance, service_user, peer_added, was_registered)
		raise TunnelRegistrationError(f"Register failed for '{instance.region}': {exception}") from exception

	return {"ok": True, "tunnel_ip": tunnel_ip, "tunnel_status": "Active"}


def _register_local(instance) -> dict:
	"""Local-dev registration without a tunnel (Atlas Instance.skip_tunnel). Do only the
	identity half — admin_ping, mint the scoped service user + creds — then push those to
	Atlas with skip_tunnel set so it stores them without bringing up wg0 or locking its
	firewall. No hub, no tunnel_ip allocation, no peering, no over-the-tunnel confirm.
	The data path stays on the public base_url (tunnel_url is never set), and tunnel_status
	stays Inactive. There is nothing host-side to roll back, so a failure just propagates."""
	client = AtlasClient(instance)
	client.admin_ping(instance.base_url)

	service_user = _ensure_service_user(instance)
	api_key, api_secret = _rotate_service_credentials(service_user)
	webhook_secret = _rotate_webhook_secret(instance)

	client.link_local(
		instance.base_url,
		{
			"central_url": frappe.utils.get_url(),
			"service_api_key": api_key,
			"service_api_secret": api_secret,
			"service_webhook_secret": webhook_secret,
		},
	)

	instance.service_user = service_user
	instance.tunnel_status = "Inactive"
	instance.save(ignore_permissions=True)

	return {"ok": True, "tunnel_status": "Inactive", "skip_tunnel": True}


def _ensure_service_user(instance) -> str:
	"""Get-or-create the dedicated, scoped Central user this Atlas authenticates as when
	it calls in (`atlas-<region>@<central-site>`). Its only role is `Atlas Service`
	(desk-less) — it holds no operator powers; the inbound event/sizes/images/ping
	endpoints are all it ever needs to reach."""
	email = _service_user_email(instance.region)
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"Atlas {instance.region}",
				"user_type": "System User",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	_ensure_service_role(user)
	return user.name


def _ensure_service_role(user) -> None:
	"""Ensure the desk-less `Atlas Service` role exists and the user carries only it."""
	if not frappe.db.exists("Role", SERVICE_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": SERVICE_ROLE, "desk_access": 0}).insert(
			ignore_permissions=True
		)
	if SERVICE_ROLE not in {row.role for row in (user.get("roles") or [])}:
		user.append("roles", {"role": SERVICE_ROLE})
		user.save(ignore_permissions=True)


def _rotate_service_credentials(user_name: str) -> tuple[str, str]:
	"""Generate a fresh API key/secret for the service user (rotation = re-register) and
	return them so provision_tunnel can push them to Atlas. The secret is stored
	encrypted on the User; only this plaintext copy leaves Central."""
	api_key = frappe.generate_hash(length=20)
	api_secret = frappe.generate_hash(length=20)
	user = frappe.get_doc("User", user_name)
	user.api_key = api_key
	user.api_secret = api_secret
	user.save(ignore_permissions=True)
	return api_key, api_secret


def _rotate_webhook_secret(instance) -> str:
	"""Fresh signing secret, in-memory only — the caller's save() persists it. A direct DB
	write would be wiped: _save_passwords() clears Password fields reading empty."""
	secret = frappe.generate_hash(length=32)
	instance.webhook_secret = secret
	return secret


def _verify_over_tunnel(client, tunnel_url: str, attempts: int = 8, delay: float = 2.0) -> None:
	"""Ping the Atlas over wg0 until it answers. The hub adds the peer immediately
	before this, so the first packet triggers the WireGuard handshake and can race it
	(connection reset / incomplete read). Retry a handful of times so a freshly-dialled
	tunnel gets a moment to settle before we treat it as unreachable and roll back."""
	last: Exception | None = None
	for attempt in range(attempts):
		try:
			client.admin_ping(tunnel_url)
			return
		except Exception as exception:
			last = exception
			if attempt < attempts - 1:
				time.sleep(delay)
	raise last  # type: ignore[misc]


def _peer_endpoint(base_url: str, listen_port: int) -> str:
	"""The Atlas's public wg endpoint the hub dials: the host of base_url with the wg
	listen port (https://blr.atlas.example.com → blr.atlas.example.com:51820)."""
	host = urlparse(base_url).hostname
	if not host:
		frappe.throw(
			_("Cannot derive a wg endpoint from base_url '{0}'.").format(base_url), TunnelRegistrationError
		)
	return f"{host}:{listen_port}"


def _slug(text: str) -> str:
	return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _service_user_email(region: str) -> str:
	"""Build a valid service-user address for both hosted and local site names."""
	site = frappe.local.site
	domain = site if "." in site else f"{_slug(site)}.local"
	return f"atlas-{_slug(region)}@{domain}"


def _rollback(instance, service_user: str | None, peer_added: bool, was_registered: bool) -> None:
	"""Undo the Central-side half of a failed registration. Atlas's armed auto-revert
	restores its own public firewall and tears its tunnel on its own, so we only remove
	the half-added hub peer + the runtime tunnel state. If the instance was ALREADY
	registered (a re-tunnel that failed) we keep its identity and fall back to Inactive;
	a first registration that fails is torn down to Unregistered (delete the new service
	user). Best-effort: cleanup failures are logged, not raised."""
	if peer_added and instance.peer_public_key:
		try:
			run_host_task(
				script="hub-peer-remove.py",
				variables={"PEER_PUBLIC_KEY": instance.peer_public_key},
			)
		except Exception:
			frappe.log_error(title=f"Tunnel rollback: hub-peer-remove failed for {instance.region}")

	instance.db_set("peer_public_key", None)
	instance.db_set("peer_endpoint", None)

	if was_registered:
		# keep service_user and tunnel_ip — only the tunnel failed to come up.
		instance.db_set("tunnel_status", "Inactive")
	else:
		instance.db_set("service_user", None)
		instance.db_set("tunnel_status", "Unregistered")
		if service_user and frappe.db.exists("User", service_user):
			try:
				frappe.delete_doc("User", service_user, ignore_permissions=True, force=True)
			except Exception:
				frappe.log_error(title=f"Tunnel rollback: service-user cleanup failed for {instance.region}")

	# nosemgrep: frappe-manual-commit -- hub-peer-add (run_host_task) already committed the
	# half-provisioned state; the caller re-raises, on which Frappe rolls the request back. Commit
	# the cleanup here so the half state can't survive that rollback — no limbo.
	frappe.db.commit()


def remove_tunnel(instance) -> dict:
	"""Strip an Atlas's tunnel + management firewall while keeping it REGISTERED (the
	operator's Remove Tunnel button). Tells Atlas to revert its firewall + drop wg0 and
	removes the hub peer, but RETAINS the registration identity — the scoped service
	user and the allocated tunnel_ip — and sets status to Inactive. Register
	brings the tunnel back up (re-tunnel). The data path falls back to the public
	base_url while Inactive (only Active routes over tunnel_url).

	Best-effort throughout: a teardown must not hard-fail and strand half state. The
	Atlas call goes over the tunnel while Active; Atlas reverts the firewall (reopening
	public) before dropping wg0, so the response races the teardown — a dropped
	connection is expected and tolerated, re-verified over the now-public base_url."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if instance.tunnel_status in ("Active", "Provisioning"):
		client = AtlasClient(instance)
		over = (
			instance.tunnel_url
			if (instance.tunnel_status == "Active" and instance.tunnel_url)
			else instance.base_url
		)
		try:
			client.deprovision_tunnel(over)
		except Exception:
			# firewall-revert + tunnel-down commit host-side; dropping wg0 mid-call kills
			# the response. Confirm Atlas is reachable publicly again (firewall reverted)
			# before trusting the teardown; if even that fails, log and finish the cleanup.
			try:
				client.admin_ping(instance.base_url)
			except Exception:
				frappe.log_error(title=f"Remove tunnel: {instance.region} unconfirmed after deprovision")

	if instance.peer_public_key:
		try:
			run_host_task(
				script="hub-peer-remove.py",
				variables={"PEER_PUBLIC_KEY": instance.peer_public_key},
			)
		except Exception:
			frappe.log_error(title=f"Remove tunnel: hub-peer-remove failed for {instance.region}")

	# Keep service_user / tunnel_ip — only the runtime tunnel is torn down.
	instance.db_set("peer_public_key", None)
	instance.db_set("peer_endpoint", None)
	instance.db_set("tunnel_status", "Inactive")

	# nosemgrep: frappe-manual-commit -- hub-peer-remove (run_host_task) already committed; persist
	# the teardown durably so a later error in the request can't resurrect the torn-down state.
	frappe.db.commit()
	return {"ok": True, "tunnel_status": "Inactive"}
