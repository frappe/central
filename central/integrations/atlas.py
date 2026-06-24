from __future__ import annotations

import re
from urllib.parse import urlparse

import frappe
from frappe.frappeclient import FrappeClient

from central.central.doctype.asset.asset import Asset
from central.host_task import run_host_task

# Central's integration with the regional Atlas clusters (Edge B), all in one place:
#   - outbound: AtlasClient calls Atlas over Frappe's FrappeClient (token auth from
#     the per-instance API key/secret on the Atlas Instance record).
#   - inbound: the Asset mirror is kept fresh two ways — Atlas pushes lifecycle
#     events to ingest_event (low latency), and reconcile pulls the authoritative
#     list to correct drift. The Asset controller is the mirror's sole writer; this
#     module only decides when and from where.


# --- outbound: Central → Atlas ----------------------------------------------


class AtlasError(frappe.ValidationError):
	pass


def get_atlas_instance(region: str):
	"""Resolve a region (= cluster) to its `Atlas Instance`, or raise."""
	name = frappe.db.get_value("Atlas Instance", {"region": region})
	if not name:
		frappe.throw(f"No Atlas registered for region '{region}'.", AtlasError)
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
		(spec/19-tunnel.md § Credentials); the target is the tunnel_url over wg0 once the
		tunnel is Active, and the public base_url only during bootstrap."""
		if self.instance.status == "Disabled":
			frappe.throw(f"Atlas '{self.instance.region}' is disabled.", AtlasError)
		return self._admin_client(self._data_url())

	def _data_url(self) -> str:
		if self.instance.tunnel_status == "Active" and self.instance.tunnel_url:
			return self.instance.tunnel_url
		return self.instance.base_url

	def ping(self) -> dict:
		"""Reachability + auth check against the frappe ping endpoint."""
		return self.client().get_api("ping")

	def vm_action(self, name: str, method: str) -> str:
		"""Invoke a Virtual Machine lifecycle method (start/stop/terminate) as the
		operator; return the resulting Task name."""
		return self.client().post_api(
			"run_doc_method", params={"dt": "Virtual Machine", "dn": name, "method": method}
		)

	def create_vm(
		self,
		*,
		central_reference: str,
		title: str,
		vcpus: int,
		memory_megabytes: int,
		disk_gigabytes: int,
		email: str | None = None,
		cpu_max_cores: float | None = None,
	) -> dict:
		"""Provision a VM on this Atlas for a Central team (the operator write).
		Returns the new VM in the Asset-mirror shape so the caller can upsert it."""
		params: dict = {
			"central_reference": central_reference,
			"title": title,
			"vcpus": vcpus,
			"memory_megabytes": memory_megabytes,
			"disk_gigabytes": disk_gigabytes,
		}
		if email:
			params["email"] = email
		if cpu_max_cores:
			params["cpu_max_cores"] = cpu_max_cores
		return self.client().post_api("atlas.atlas.api.provision.create_vm", params=params)

	def central_vms(self, central_reference: str | None = None) -> list[dict]:
		"""Tenant-tagged VMs on this Atlas for the mirror reconcile (optionally one
		team). One dict per VM: name, central_reference, status, gateway_url."""
		params = {"central_reference": central_reference} if central_reference else None
		return self.client().get_api("atlas.atlas.api.inventory.tenant_vms", params)

	# --- admin-auth path: the registration handshake (TUNNEL.md) -------------
	# Central→Atlas registration uses the Atlas ADMIN creds (not the per-Atlas service
	# creds the data path uses today). provision_tunnel goes over the public base_url;
	# the verify ping and confirm_tunnel go over the tunnel_url, so reaching them is
	# itself the proof that wg0 works before the public side is locked for good.

	def _admin_client(self, base_url: str) -> FrappeClient:
		if not self.instance.admin_api_key:
			frappe.throw(f"Atlas '{self.instance.region}' has no admin API key.", AtlasError)
		return FrappeClient(
			base_url,
			api_key=self.instance.admin_api_key,
			api_secret=self.instance.get_password("admin_api_secret"),
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

	def confirm_tunnel(self, tunnel_url: str) -> dict:
		"""Atlas inbound confirm_tunnel OVER the tunnel (admin auth): Atlas persists the
		lockdown and cancels its auto-revert. Returns { tunnel_status }."""
		return self._admin_client(tunnel_url).post_api(
			"atlas.atlas.api.central_link.confirm_tunnel", params={}
		)


# --- inbound push: webhook events (central.api.atlas.event delegates here) ---


def ingest_event(atlas_id: str, event_type: str, payload: dict, occurred_at) -> dict:
	"""
	Verify the sender, then queue the mirror write so Atlas gets a fast ack. The
	write runs in a background job — it's idempotent and last-writer-wins, and the
	periodic reconcile is the backstop if a job is ever lost. ping and unknown event
	types have nothing to mirror, so they're acknowledged without queuing.
	"""

	cluster = _atlas_cluster(atlas_id)

	if event_type not in _EVENT_HANDLERS:
		return {"ok": True, "queued": False}

	frappe.enqueue(
		apply_event,
		queue="short",
		enqueue_after_commit=True,
		cluster=cluster,
		event_type=event_type,
		payload=payload or {},
		occurred_at=occurred_at,
	)

	return {"ok": True, "queued": True}


def apply_event(cluster: str, event_type: str, payload: dict, occurred_at) -> None:
	"""Background job: apply one verified Atlas event to the Asset mirror."""
	_EVENT_HANDLERS[event_type](cluster, payload or {}, occurred_at)


def _atlas_cluster(atlas_id: str) -> str:
	"""The cluster an event came from — and the 'known sender' check: events from
	an unregistered or disabled Atlas are refused."""
	cluster = frappe.db.get_value("Atlas Instance", {"atlas_id": atlas_id, "status": ["!=", "Disabled"]})
	if not cluster:
		frappe.throw(f"Unknown or disabled Atlas '{atlas_id}'.", frappe.PermissionError)
	return cluster


def _on_vm(cluster: str, payload: dict, occurred_at) -> None:
	Asset.mirror_vm(cluster, payload, occurred_at=occurred_at)


def _on_vm_deleted(cluster: str, payload: dict, occurred_at) -> None:
	resource_id = payload.get("name")
	if resource_id and frappe.db.exists("Asset", resource_id) and not Asset.is_stale(resource_id, occurred_at):
		Asset.mark_terminated(resource_id, last_event_at=occurred_at)


_EVENT_HANDLERS = {
	"vm.created": _on_vm,
	"vm.status_changed": _on_vm,
	"vm.deleted": _on_vm_deleted,
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
			stale.append(name)
	return {"synced": synced, "stale": stale}


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
	tunnel_ip; 3. mint atlas_id + the scoped service user; 4. provision_tunnel over
	base_url; 5. hub-peer-add on the hub; 6. ping at tunnel_ip over wg0; 7.
	confirm_tunnel over the tunnel; 8. tunnel_status=Active. Any failure before confirm
	rolls back the Central-side half and raises TunnelRegistrationError; the instance
	stays Unregistered (Atlas's auto-revert reopens its own firewall)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw("Not permitted.", frappe.PermissionError)
	if not (instance.admin_api_key and instance.get_password("admin_api_secret", raise_exception=False)):
		frappe.throw("Set the Atlas admin API key and secret before registering.", TunnelRegistrationError)

	settings = frappe.get_single("Central Tunnel Settings")
	if settings.hub_status != "Active":
		frappe.throw("Initialize the hub before registering an Atlas.", TunnelRegistrationError)

	client = AtlasClient(instance)

	# 1. Prove the public bootstrap path + admin creds before changing anything.
	client.admin_ping(instance.base_url)

	# 2-3. Allocate the tunnel address and mint the scoped service identity. Reuse an
	# existing allocation/id on re-register so the Atlas keeps a stable address.
	tunnel_ip = instance.tunnel_ip or settings.allocate_tunnel_ip()
	atlas_id = instance.atlas_id or frappe.generate_hash(length=12)
	service_user = _ensure_service_user(instance)
	api_key, api_secret = _rotate_service_credentials(service_user)

	peer_added = False
	try:
		# 4. Atlas brings up wg0 + arms its firewall, returns its public key + port.
		provision = client.provision_tunnel(
			instance.base_url,
			{
				"atlas_id": atlas_id,
				"hub_public_key": settings.hub_public_key,
				"hub_endpoint": settings.hub_endpoint,
				"tunnel_ip": tunnel_ip,
				"tunnel_cidr": settings.tunnel_cidr,
				"central_url": frappe.utils.get_url(),
				"service_api_key": api_key,
				"service_api_secret": api_secret,
			},
		)
		peer_public_key = provision["wg_public_key"]
		peer_endpoint = _peer_endpoint(instance.base_url, provision["listen_port"])

		instance.atlas_id = atlas_id
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

		# 6. Verify reachability over wg0, then 7. confirm over the tunnel.
		client.admin_ping(instance.tunnel_url)
		client.confirm_tunnel(instance.tunnel_url)

		# 8. The lockdown is now proven safe to keep.
		instance.tunnel_status = "Active"
		instance.save(ignore_permissions=True)
	except Exception as exception:
		_rollback(instance, service_user, peer_added)
		raise TunnelRegistrationError(f"Register failed for '{instance.region}': {exception}") from exception

	return {"ok": True, "atlas_id": atlas_id, "tunnel_ip": tunnel_ip, "tunnel_status": "Active"}


def _ensure_service_user(instance) -> str:
	"""Get-or-create the dedicated, scoped Central user this Atlas authenticates as when
	it calls in (`atlas-<region>@<central-site>`). Its only role is `Atlas Service`
	(desk-less) — it holds no operator powers; the inbound event/sizes/images/ping
	endpoints are all it ever needs to reach."""
	email = f"atlas-{_slug(instance.region)}@{frappe.local.site}"
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


def _peer_endpoint(base_url: str, listen_port: int) -> str:
	"""The Atlas's public wg endpoint the hub dials: the host of base_url with the wg
	listen port (https://blr.atlas.example.com → blr.atlas.example.com:51820)."""
	host = urlparse(base_url).hostname
	if not host:
		frappe.throw(f"Cannot derive a wg endpoint from base_url '{base_url}'.", TunnelRegistrationError)
	return f"{host}:{listen_port}"


def _slug(text: str) -> str:
	return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _rollback(instance, service_user: str | None, peer_added: bool) -> None:
	"""Undo the Central-side half of a failed registration. Atlas's armed auto-revert
	restores its own public firewall and tears its tunnel on its own, so we only remove
	the half-added hub peer and the scoped service user, and return the instance to
	Unregistered. Best-effort: cleanup failures are logged, not raised — the original
	error is the one worth surfacing."""
	if peer_added and instance.peer_public_key:
		try:
			run_host_task(
				script="hub-peer-remove.py",
				variables={"PEER_PUBLIC_KEY": instance.peer_public_key},
			)
		except Exception:
			frappe.log_error(title=f"Tunnel rollback: hub-peer-remove failed for {instance.region}")

	instance.db_set("service_user", None)
	instance.db_set("peer_public_key", None)
	instance.db_set("peer_endpoint", None)
	instance.db_set("tunnel_status", "Unregistered")

	if service_user and frappe.db.exists("User", service_user):
		try:
			frappe.delete_doc("User", service_user, ignore_permissions=True, force=True)
		except Exception:
			frappe.log_error(title=f"Tunnel rollback: service-user cleanup failed for {instance.region}")

	# nosemgrep: frappe-manual-commit -- hub-peer-add (run_host_task) already committed the
	# half-provisioned state; the caller re-raises, on which Frappe rolls the request back. Commit
	# the cleanup here so the half state can't survive that rollback — no Unregistered/orphan limbo.
	frappe.db.commit()
