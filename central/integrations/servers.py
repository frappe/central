from __future__ import annotations

import time

import frappe
from frappe import _

from central.errors import AtlasConnectionError, AtlasResourceGone
from central.iam import can_on_any_server
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.infrastructure.doctype.site.site import Site
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.atlas import AtlasClient

# A resize may move the VM to another host, so the wait is generous enough to cover a migration.
POWER_WAIT_SECONDS = 15 * 60
POWER_POLL_SECONDS = 5


def observe_server(server: VirtualMachine) -> str:
	"""Read the owning region and record what it reports about this Team's server."""
	client = get_client(server)
	try:
		remote = client.get_vm(server.atlas_vm_id)
	except AtlasResourceGone:
		mark_terminated(server)
		ResourceAction.confirm_observed_status(server.name, "Terminated")
		return "Terminated"

	if remote.get("id") != server.atlas_vm_id or remote.get("tenant_id") != client.tenant_id:
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
		for value in (compute.get("cpu_millicores"), compute.get("memory_mib"), disk.get("size_mib"))
	):
		raise AtlasConnectionError(_("Atlas returned invalid server resource sizes."))

	# The regional proxy derives a VM's admin hostname from its mesh address, so Central
	# builds the gateway itself. An unenrolled pilot has nothing to sign into yet.
	gateway = None
	if frappe.db.exists("Pilot Credential", {"server": server.name, "team": server.team, "status": "Active"}):
		gateway = frappe.get_cached_doc("Region", server.region).get_vm_gateway_url(network.get("mesh_ipv6"))

	VirtualMachine.record_observed_state(
		server.name,
		frappe.utils.now_datetime(),
		{
			"status": status,
			"vcpus": compute["cpu_millicores"] // 1000,
			"memory_megabytes": compute["memory_mib"],
			"disk_gigabytes": disk["size_mib"] / 1024,
			"ipv6_address": network.get("mesh_ipv6"),
			"public_ipv4": network.get("public_ipv4"),
			# Atlas reports the guest's public IPv6 as a prefix. A /128 is one address.
			"public_ipv6": (network.get("public_ipv6") or "").removesuffix("/128") or None,
			"gateway_url": gateway,
		},
	)

	# The wildcard gateway already routes here. Pilot only needs to replace its local
	# admin.local hostname with the routed name.
	frappe.get_doc("Virtual Machine", server.name).claim_admin_hostname()

	# A Pilot machine carries a site, and this report is where its address arrives.
	Site.create_once_addressable(server.name)
	ResourceAction.confirm_observed_status(server.name, status)
	return status


def resize_server(server: VirtualMachine, shape: dict) -> None:
	"""Apply a new size on Atlas, then start the server.

	A CPU or memory change needs a stopped VM and may move it to a host that fits (a
	`migrating` state during the wait), so it stops the VM and sends CPU, memory and disk in
	one resize. A disk-only grow uses the online disk API, because the resize API needs a
	stopped VM for a disk change too. Every call sets absolute values, so repeating the
	resize is safe. A resized server has outgrown the hobby idle shutdown, so both paths
	turn it off."""
	client = get_client(server)
	remote = client.get_vm(server.atlas_vm_id)
	compute, disk = remote.get("compute") or {}, remote.get("disk") or {}
	cpu_millicores = shape["vcpus"] * 1000
	memory_mib = shape["memory_megabytes"]
	disk_mib = shape["disk_gigabytes"] * 1024

	reshaping = (compute.get("cpu_millicores"), compute.get("memory_mib")) != (cpu_millicores, memory_mib)
	if reshaping:
		wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")
		client.resize(server.atlas_vm_id, cpu_millicores, memory_mib, disk_mib)
	else:
		if disk_mib > (disk.get("size_mib") or 0):
			client.update_disk(server.atlas_vm_id, disk_mib)
		if compute.get("sleep_after_idle_seconds"):
			client.disable_idle_shutdown(server.atlas_vm_id)

	wait_for_power_state(client, server.atlas_vm_id, "start", "running")
	observe_server(server)


def wait_for_power_state(client: AtlasClient, vm_id: str, action: str, state: str) -> None:
	"""Wait until Atlas observes the VM in `state`, sending the power action once the VM is in
	a stable state. A `migrating` or `pending` VM is left to settle first — Atlas may be moving
	it to another host during a resize — and is never told to change power mid-transition."""
	deadline = time.monotonic() + POWER_WAIT_SECONDS
	acted = False
	while True:
		current = client.get_vm(vm_id).get("current_state")
		if current == state:
			return
		if not acted and current not in ("migrating", "pending"):
			client.vm_action(vm_id, action)
			acted = True
		if time.monotonic() > deadline:
			frappe.throw(
				_("The server did not reach the {0} state in time.").format(state), AtlasConnectionError
			)
		time.sleep(POWER_POLL_SECONDS)


def reconcile(team: str | None = None) -> dict:
	"""Enqueue a scoped read for each server Central owns, oldest report first. Never
	infer Team ownership from a regional list."""
	if team and not can_on_any_server(frappe.session.user, team, "server:view"):
		frappe.throw(_("You cannot refresh this Team's servers."), frappe.PermissionError)

	filters = {"status": ["!=", "Terminated"], "atlas_vm_id": ["is", "set"]}
	if team:
		filters["team"] = team

	servers = frappe.get_all(
		"Virtual Machine", filters=filters, pluck="name", limit=100, order_by="state_observed_at asc"
	)
	for name in servers:
		frappe.enqueue(
			"central.integrations.servers.refresh_server",
			name=name,
			enqueue_after_commit=True,
			job_id=f"server-refresh:{name}",
			deduplicate=True,
		)

	return {"synced": [], "stale": [], "queued": len(servers)}


def get_console_url(server: VirtualMachine) -> str:
	"""Return a single-use Atlas web console URL for a running Ubuntu server.

	Atlas opens the session over SSH with a key it pushes for that session only."""
	if server.image_offering != "ubuntu":
		frappe.throw(_("The web console is available only for Ubuntu servers."))
	if server.status != "Running":
		frappe.throw(_("Start the server before you open its console."))

	return get_client(server).get_console_url(server.atlas_vm_id, mode="ssh")


def refresh_server(name: str) -> None:
	server = frappe.get_doc("Virtual Machine", name, for_update=True)
	if server.status != "Terminated":
		observe_server(server)


def get_client(server: VirtualMachine) -> AtlasClient:
	if not server.atlas_vm_id:
		frappe.throw(_("This server has no verified regional VM identity."))

	instance = frappe.get_cached_doc("Region", server.region)
	tenant_id = frappe.db.get_value("Team", server.team, "tenant_id")
	return AtlasClient(instance, tenant_id)


def mark_terminated(server: VirtualMachine) -> None:
	"""Record a server as gone and revoke the pilot credentials bound to it."""
	server.status = "Terminated"
	VirtualMachine.mark_terminated(server.name)
	credentials = frappe.get_all(
		"Pilot Credential", filters={"team": server.team, "server": server.name}, pluck="name"
	)
	for name in credentials:
		PilotCredential.revoke_by_id(name)
