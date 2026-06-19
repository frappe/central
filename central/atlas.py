from __future__ import annotations

import frappe

from central.atlas_client import AtlasClient
from central.iam import can, get_user_team_names

# Edge B → the Asset mirror. Central holds a read model of each team's VMs as
# Asset rows, kept fresh two ways: Atlas pushes lifecycle events to the
# `central.api.event` webhook (low latency), and a periodic reconcile pulls the
# authoritative list to correct any drift the push missed. Source of truth stays
# in Atlas; both paths share one idempotent, last-writer-wins upsert. The Asset
# mirrors the VM verbatim (its `status` is the Atlas status as-is). The command
# path (Central → Atlas) lives at the bottom of this module.


def _resolve_team(user: str, team: str | None) -> str:
	if team:
		return team
	teams = get_user_team_names(user)
	if len(teams) != 1:
		frappe.throw("Specify a team.", frappe.ValidationError)
	return teams[0]


# --- the shared upsert ------------------------------------------------------


def _is_stale(resource_id: str, occurred_at) -> bool:
	"""Last-writer-wins: True if we've already applied a newer event for this VM."""
	last = frappe.db.get_value("Asset", resource_id, "last_event_at")
	return bool(last and occurred_at and frappe.utils.get_datetime(last) > frappe.utils.get_datetime(occurred_at))


def _mirror_vm(cluster: str, vm: dict, *, occurred_at=None, synced_at=None) -> None:
	"""Upsert one VM into the Asset mirror — shared by the event push (pass
	`occurred_at`, which drives LWW) and the reconcile pull (pass `synced_at`). A
	VM with no team (`central_reference`) belongs to no team's mirror and is
	skipped."""
	resource_id, team = vm.get("name"), vm.get("central_reference")
	if not resource_id or not team or not frappe.db.exists("Team", team):
		return
	exists = frappe.db.exists("Asset", resource_id)
	if exists and occurred_at and _is_stale(resource_id, occurred_at):
		return
	doc = frappe.get_doc("Asset", resource_id) if exists else frappe.new_doc("Asset")
	doc.resource_id = resource_id
	doc.team = team
	doc.cluster = cluster
	doc.status = vm.get("status") or "Pending"
	doc.title = vm.get("title")
	doc.vcpus = vm.get("vcpus")
	doc.memory_megabytes = vm.get("memory_megabytes")
	doc.disk_gigabytes = vm.get("disk_gigabytes")
	doc.ipv6_address = vm.get("ipv6_address")
	doc.public_ipv4 = vm.get("public_ipv4")
	doc.gateway_url = vm.get("gateway_url") or None
	if occurred_at:
		doc.last_event_at = occurred_at
	if synced_at:
		doc.last_synced_at = synced_at
	# System write: Asset is a read-only mirror (users can't write it); the sync
	# is the sole writer, authorized by the verified Atlas event, not desk RBAC.
	doc.save(ignore_permissions=True)


# --- push: inbound events (central.api.event delegates here) ----------------


def _atlas_cluster(atlas_id: str) -> str:
	"""The cluster (Atlas Instance) an event came from — and the 'known sender'
	check: events from an unregistered or disabled Atlas are refused."""
	cluster = frappe.db.get_value("Atlas Instance", {"atlas_id": atlas_id, "status": ["!=", "Disabled"]})
	if not cluster:
		frappe.throw(f"Unknown or disabled Atlas '{atlas_id}'.", frappe.PermissionError)
	return cluster


def _on_ping(cluster: str, payload: dict, occurred_at) -> None:
	print("ping", cluster, payload, occurred_at)


def _on_vm(cluster: str, payload: dict, occurred_at) -> None:
	_mirror_vm(cluster, payload, occurred_at=occurred_at)


def _on_vm_deleted(cluster: str, payload: dict, occurred_at) -> None:
	resource_id = payload.get("name")
	if resource_id and frappe.db.exists("Asset", resource_id) and not _is_stale(resource_id, occurred_at):
		frappe.db.set_value("Asset", resource_id, {"status": "Terminated", "last_event_at": occurred_at})


_EVENT_HANDLERS = {
	"ping": _on_ping,
	"vm.created": _on_vm,
	"vm.status_changed": _on_vm,
	"vm.deleted": _on_vm_deleted,
}


def ingest_event(atlas_id: str, event_type: str, payload: dict, occurred_at) -> dict:
	"""Apply one verified Atlas event to the mirror, dispatched by type. Unknown
	types are acknowledged and ignored (forward-compatible)."""
	cluster = _atlas_cluster(atlas_id)
	handler = _EVENT_HANDLERS.get(event_type)
	if handler:
		handler(cluster, payload or {}, occurred_at)
	return {"ok": True, "handled": bool(handler)}


# --- pull: reconcile (periodic + manual backstop) ---------------------------


def reconcile_atlas(instance, team: str | None = None) -> int:
	"""Pull the authoritative VM list from one Atlas and sync the mirror: upsert
	each, then mark vanished ones Terminated. Optionally scope to one team."""
	now = frappe.utils.now_datetime()
	vms = AtlasClient(instance).central_vms(team)
	seen = {vm.get("name") for vm in vms}
	for vm in vms:
		_mirror_vm(instance.name, vm, synced_at=now)
	gone = {"cluster": instance.name, "status": ["!=", "Terminated"]}
	if team:
		gone["team"] = team
	for resource_id in frappe.get_all("Asset", filters=gone, pluck="name"):
		if resource_id not in seen:
			frappe.db.set_value("Asset", resource_id, {"status": "Terminated", "last_synced_at": now})
	return len(vms)


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


# --- read + manual refresh (dashboard) --------------------------------------


@frappe.whitelist(methods=["GET"])
def registry(team: str | None = None) -> dict:
	"""List a team's VMs from the Asset mirror — a pure read. Gated on `cluster:view`."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't view this team's clusters.", frappe.PermissionError)
	assets = frappe.get_all(
		"Asset",
		filters={"team": team},
		fields=[
			"resource_id",
			"title",
			"cluster",
			"status",
			"vcpus",
			"memory_megabytes",
			"disk_gigabytes",
			"ipv6_address",
			"public_ipv4",
			"gateway_url",
			"last_synced_at",
		],
		order_by="cluster asc, resource_id asc",
	)
	return {"team": team, "assets": assets}


@frappe.whitelist(methods=["GET"])
def list_instances(team: str | None = None) -> list[dict]:
	"""List the regions a team can place servers in — every Active Atlas Instance.
	A pure read used by the console's New Server region picker. Gated on
	`cluster:view` (same scope as `registry`); the team only resolves the gate,
	the region set itself is team-agnostic."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't view clusters for this team.", frappe.PermissionError)
	# Atlas Instance is global infrastructure that also holds the per-instance API
	# credentials, so the DocType is locked to System Manager. Regions aren't
	# user/team-scoped, and `cluster:view` already authorizes this read, so we
	# bypass DocType RBAC and curate the safe, non-secret fields here — otherwise
	# a Central User (e.g. a team Owner) gets an empty list.
	return frappe.get_all(
		"Atlas Instance",
		filters={"status": "Active"},
		fields=["region", "status", "reachable"],
		order_by="region asc",
		ignore_permissions=True,
	)


@frappe.whitelist(methods=["POST"])
def refresh_assets(team: str | None = None) -> dict:
	"""Manually reconcile this team's mirror from every Active Atlas — the on-demand
	twin of the scheduled reconcile. Gated on `cluster:view`."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't refresh this team's clusters.", frappe.PermissionError)
	return reconcile(team)


# --- command path: Central drives Atlas -------------------------------------
# Capability-gated here (Atlas stays policy-unaware); Central calls Atlas as the
# operator. Lifecycle methods act on an existing asset by id.


def _run_command(action: str, capability: str, atlas_method: str, team: str | None, resource_id: str | None) -> dict:
	"""Shared lifecycle path (start/stop/terminate): gate on `capability`,confirm
	the asset belongs to the team, call Atlas, return the Task handle.
	"""
	user = frappe.session.user
	team = _resolve_team(user, team)

	# capability check
	if not can(user, team, capability):
		frappe.throw(f"You can't {action} servers for this team.", frappe.PermissionError)

	if not resource_id:
		frappe.throw("resource_id is required.", frappe.ValidationError)

	# Ownership: the asset must be in this team's mirror — also how we route to
	# the right Atlas (its cluster).
	cluster = frappe.db.get_value("Asset", {"resource_id": resource_id, "team": team}, "cluster")
	if not cluster:
		frappe.throw(f"No server '{resource_id}' for this team.", frappe.DoesNotExistError)

	instance = frappe.get_doc("Atlas Instance", cluster)

	task = AtlasClient(instance).vm_action(resource_id, atlas_method)

	return {"resource_id": resource_id, "task": task}


@frappe.whitelist(methods=["POST"])
def start_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Start a stopped server. Gated on `server:power`."""
	return _run_command("start", "server:power", "start", team, resource_id)


@frappe.whitelist(methods=["POST"])
def stop_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Stop a running server. Gated on `server:power`."""
	return _run_command("stop", "server:power", "stop", team, resource_id)


@frappe.whitelist(methods=["POST"])
def terminate_server(team: str | None = None, resource_id: str | None = None) -> dict:
	"""Terminate a server. Gated on `server:terminate`."""
	return _run_command("terminate", "server:terminate", "terminate", team, resource_id)


@frappe.whitelist(methods=["POST"])
def create_server(
	team: str | None = None,
	region: str | None = None,
	title: str | None = None,
	vcpus: int | None = None,
	memory_megabytes: int | None = None,
	disk_gigabytes: int | None = None,
	cpu_max_cores: float | None = None,
) -> dict:
	"""Provision a new server for a team in a region. Gated on `server:create`.

	`region` is an Atlas Instance (one Atlas = one region), which is also how we
	route the provision call. Atlas owns placement/image/lifecycle; we pass the
	team (as the tenant's central_reference) and the chosen size. The returned VM
	is upserted into the Asset mirror right away so it appears in the registry
	without waiting for the next reconcile/event.
	"""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "server:create"):
		frappe.throw("You can't create servers for this team.", frappe.PermissionError)
	if not region:
		frappe.throw("region is required.", frappe.ValidationError)

	client = AtlasClient.for_region(region)
	# Seed the Atlas tenant (first use) with the team owner's email.
	email = frappe.db.get_value("Team", team, "owner_user")

	vm = client.create_vm(
		central_reference=team,
		title=title or "server",
		vcpus=int(vcpus or 1),
		memory_megabytes=int(memory_megabytes or 512),
		disk_gigabytes=int(disk_gigabytes or 10),
		email=email,
		cpu_max_cores=cpu_max_cores,
	)

	_mirror_vm(client.instance.name, vm, synced_at=frappe.utils.now_datetime())
	return {"resource_id": vm.get("name"), "server": vm}
