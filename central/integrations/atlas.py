from __future__ import annotations

import frappe
from frappe.frappeclient import FrappeClient

from central.central.doctype.asset.asset import Asset

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
		if self.instance.status == "Disabled":
			frappe.throw(f"Atlas '{self.instance.region}' is disabled.", AtlasError)
		return FrappeClient(
			self.instance.base_url,
			api_key=self.instance.api_key,
			api_secret=self.instance.get_password("api_secret"),
		)

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
