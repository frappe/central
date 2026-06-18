from __future__ import annotations

import frappe

from central.atlas_client import AtlasClient, stub_vm_inventory
from central.iam import can, get_user_team_names, user_has_operator_bypass

# Edge B → registry mirror. Central holds a read model of each team's VMs as Asset
# rows. `registry` is a pure read of that mirror; `refresh_assets` (a POST) syncs it
# from every Active Atlas. Source of truth stays in Atlas.


def _inventory(instance, team: str) -> list[dict]:
	"""Team's VMs in one cluster. Real Atlas call, or the dev stub when the
	`atlas_use_stub_inventory` flag is set — never fabricated data in prod."""
	if frappe.conf.get("atlas_use_stub_inventory"):
		return stub_vm_inventory(team)
	return AtlasClient(instance).list_vms(team)


def _upsert_asset(team: str, cluster: str, vm: dict, now) -> None:
	rid = vm["resource_id"]
	doc = frappe.get_doc("Asset", rid) if frappe.db.exists("Asset", rid) else frappe.new_doc("Asset")
	doc.resource_id = rid
	doc.team = team
	doc.cluster = cluster
	doc.status = vm.get("status") or "Provisioning"
	doc.gateway_url = vm.get("gateway_url") or None
	doc.last_synced_at = now
	doc.save(ignore_permissions=True)


def sync_team_assets(team: str) -> dict:
	"""Mirror a team's VMs from every Active Atlas into Asset rows. Fail-soft: a
	cluster that errors is reported in `stale`, leaving its last-known mirror intact."""
	now = frappe.utils.now_datetime()
	synced, stale = [], []
	for region in frappe.get_all("Atlas Instance", filters={"status": "Active"}, pluck="name"):
		instance = frappe.get_doc("Atlas Instance", region)
		try:
			vms = _inventory(instance, team)
		except Exception:
			frappe.log_error(title=f"Atlas inventory sync failed: {region}")
			stale.append(region)
			continue
		for vm in vms:
			_upsert_asset(team, region, vm, now)
		synced.append(region)
	return {"synced": synced, "stale": stale}


def _resolve_team(user: str, team: str | None) -> str:
	if team:
		return team
	teams = get_user_team_names(user)
	if len(teams) != 1:
		frappe.throw("Specify a team.", frappe.ValidationError)
	return teams[0]


@frappe.whitelist(methods=["GET"])
def registry(team: str | None = None) -> dict:
	"""List a team's VMs from the Asset mirror — a pure read. Gated on `cluster:view`.
	The cluster is denormalized on each Asset, so no join is needed. Populate or
	refresh the mirror with `refresh_assets`."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't view this team's clusters.", frappe.PermissionError)
	assets = frappe.get_all(
		"Asset",
		filters={"team": team},
		fields=["resource_id", "cluster", "status", "gateway_url", "last_synced_at"],
		order_by="cluster asc, resource_id asc",
	)
	return {"team": team, "assets": assets}


@frappe.whitelist(methods=["POST"])
def refresh_assets(team: str | None = None) -> dict:
	"""Refresh the team's Asset mirror from every Active Atlas (writes; Frappe
	commits the POST). Gated on `cluster:view`. Returns which clusters synced vs.
	were left stale (Atlas unreachable)."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't refresh this team's clusters.", frappe.PermissionError)
	return sync_team_assets(team)


# Command path → Central drives Atlas. Capability-gated here (Atlas stays
# policy-unaware); Central calls Atlas as the operator. create stamps the team's
# Tenant; lifecycle methods act on an existing asset by id.

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
