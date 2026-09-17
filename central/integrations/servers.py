from __future__ import annotations

import frappe
from frappe import _

from central.central.doctype.asset.asset import Asset
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.central.doctype.resource_action.resource_action import GOAL_STATUS
from central.errors import (
	AtlasConnectionError,
	AtlasRequestUncertain,
	AtlasResourceGone,
	build_envelope,
	to_error_response,
)
from central.iam import can
from central.integrations.atlas import AtlasClient

CAPABILITY = {"start": "server:power", "stop": "server:power", "terminate": "server:terminate"}


def observe_server(asset: Asset) -> str:
	"""Read the owning region and record what it reports about this Team's server."""
	client = _client(asset)
	try:
		remote = client.get_vm(asset.atlas_vm_id)
	except AtlasResourceGone:
		mark_terminated(asset)
		return "Terminated"

	if remote.get("id") != asset.atlas_vm_id or remote.get("tenant_id") != client.tenant_id:
		raise AtlasConnectionError(_("Atlas returned a different server or Team."))

	state = remote.get("current_state")
	states = {
		"running": "Running",
		"stopped": "Stopped",
		"paused": "Paused",
		"unknown": "Provisioning",
		"pending": "Provisioning",
		"terminating": "Provisioning",
	}
	status = "Failed" if remote.get("error") else states.get(state)
	if not status:
		raise AtlasConnectionError(_("Atlas returned an unsupported server state."))

	compute, disk, network = remote.get("compute"), remote.get("disk"), remote.get("network")
	if not all(isinstance(value, dict) for value in (compute, disk, network)):
		raise AtlasConnectionError(_("Atlas returned incomplete server configuration."))

	if any(
		type(value) is not int or value <= 0
		for value in (compute.get("vcpus"), compute.get("memory_mib"), disk.get("size_mib"))
	):
		raise AtlasConnectionError(_("Atlas returned invalid server resource sizes."))

	# The regional proxy derives a VM's admin hostname from its mesh address, so Central
	# builds the gateway itself. An unenrolled pilot has nothing to sign into yet.
	gateway = None
	if frappe.db.exists("Pilot Credential", {"asset": asset.name, "team": asset.team, "status": "Active"}):
		gateway = frappe.get_cached_doc("Atlas Instance", asset.cluster).get_vm_gateway_url(
			network.get("mesh_ipv6")
		)

	Asset.record_observed_state(
		asset.name,
		frappe.utils.now_datetime(),
		{
			"status": status,
			"vcpus": compute["vcpus"],
			"memory_megabytes": compute["memory_mib"],
			"disk_gigabytes": disk["size_mib"] / 1024,
			"ipv6_address": network.get("mesh_ipv6"),
			"public_ipv4": network.get("public_ipv4"),
			"gateway_url": gateway,
		},
	)
	return status


def process_command(action) -> None:
	asset = frappe.get_doc("Asset", action.asset, for_update=True)
	if (
		asset.team != action.team
		or asset.cluster != action.atlas_instance
		or asset.atlas_vm_id != action.remote_vm_id
	):
		action.set_error("Failed", build_envelope("SERVER_NOT_FOUND", resource_id=action.resource_id))
		return

	if action.status == "Queued":
		if not can(action.requested_by, action.team, CAPABILITY[action.action]):
			action.set_error("Failed", build_envelope("PERMISSION_DENIED", action=action.action))
			return

		client = _client(asset)
		action.db_set({"status": "Dispatching", "dispatched_at": frappe.utils.now_datetime()})
		# The remote command can outlive this worker; recovery must never redispatch it.
		frappe.db.commit()
		try:
			client.vm_action(action.remote_vm_id, action.action)
		except AtlasRequestUncertain as error:
			action.set_error("Uncertain", to_error_response(error))
		except AtlasResourceGone as error:
			if action.action != "terminate":
				action.set_error("Failed", to_error_response(error))
				return
			mark_terminated(asset)
			action.succeed()
			return
		except AtlasConnectionError as error:
			action.set_error("Failed", to_error_response(error))
			return
		else:
			action.db_set("status", "Sent")

		frappe.db.commit()

	try:
		status = observe_server(asset)
	except AtlasConnectionError:
		action.set_error(action.status, build_envelope("REFRESH_FAILED"))
		return

	if status == GOAL_STATUS[action.action]:
		action.succeed()
	elif status in ("Failed", "Terminated"):
		action.set_error("Failed", build_envelope("ACTION_FAILED", action=action.action))
	else:
		action.db_set({"status": "In Progress", "last_checked_at": frappe.utils.now_datetime()})


def reconcile(team: str | None = None) -> dict:
	"""Enqueue a scoped read for each server Central owns, oldest report first. Never
	infer Team ownership from a regional list."""
	if team and not can(frappe.session.user, team, "server:view"):
		frappe.throw(_("You cannot refresh this Team's servers."), frappe.PermissionError)

	filters = {"status": ["!=", "Terminated"], "atlas_vm_id": ["is", "set"]}
	if team:
		filters["team"] = team

	assets = frappe.get_all(
		"Asset", filters=filters, pluck="name", limit=100, order_by="state_observed_at asc"
	)
	for name in assets:
		frappe.enqueue(
			"central.integrations.servers.refresh_server",
			name=name,
			enqueue_after_commit=True,
			job_id=f"server-refresh:{name}",
			deduplicate=True,
		)

	return {"synced": [], "stale": [], "queued": len(assets)}


def refresh_server(name: str) -> None:
	asset = frappe.get_doc("Asset", name, for_update=True)
	if asset.status != "Terminated":
		observe_server(asset)


def _client(asset: Asset) -> AtlasClient:
	if not asset.atlas_vm_id:
		frappe.throw(_("This server has no verified regional VM identity."))

	instance = frappe.get_doc("Atlas Instance", asset.cluster)
	tenant_id = frappe.db.get_value("Team", asset.team, "tenant_id")
	return AtlasClient(instance, tenant_id)


def mark_terminated(asset: Asset) -> None:
	"""Record a server as gone and revoke the pilot credentials bound to it."""
	asset.status = "Terminated"
	Asset.mark_terminated(asset.name)
	credentials = frappe.get_all(
		"Pilot Credential", filters={"team": asset.team, "asset": asset.name}, pluck="name"
	)
	for name in credentials:
		PilotCredential.revoke_by_id(name)
