from __future__ import annotations

import frappe

from central.atlas_client import AtlasClient, stub_vm_inventory
from central.iam import can, get_user_team_names, user_has_operator_bypass

# Edge B → registry mirror. `registry` is the dashboard's entry point: it pulls a
# team's VMs from every Active Atlas (cluster), mirrors them into Asset rows, and
# returns them. Source of truth stays in Atlas; Central holds a read model.


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
	"""The team's asset registry (clusters → VMs), refreshed on demand from Atlas.

	Gated on `cluster:view`. Returns the mirrored assets plus which clusters were
	freshly synced vs. served stale (Atlas unreachable)."""
	user = frappe.session.user
	team = _resolve_team(user, team)
	if not can(user, team, "cluster:view"):
		frappe.throw("You can't view this team's clusters.", frappe.PermissionError)
	freshness = sync_team_assets(team)
	assets = frappe.get_all(
		"Asset",
		filters={"team": team},
		fields=["resource_id", "cluster", "status", "gateway_url", "last_synced_at"],
		order_by="cluster asc, resource_id asc",
	)
	return {"team": team, "assets": assets, **freshness}
