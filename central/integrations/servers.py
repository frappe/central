from __future__ import annotations

import time

import frappe
from frappe import _

from central.errors import (
	AtlasConnectionError,
	AtlasRejected,
	AtlasRequestUncertain,
	AtlasResourceGone,
	build_envelope,
	to_error_response,
)
from central.iam import can, can_on_any_server
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.resource_action.resource_action import (
	ACTION_CAPABILITIES,
	ROUND_TRIP_ACTIONS,
	TERMINAL_STATES,
	ResourceAction,
)
from central.infrastructure.doctype.site.site import Site
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.atlas import AtlasClient

# A resize may move the VM to another host, so the wait is generous enough to cover a migration.
POWER_WAIT_SECONDS = 15 * 60
# A resize waits for a stop and a start, so its job must outlive both waits.
RESIZE_JOB_TIMEOUT_SECONDS = 2 * POWER_WAIT_SECONDS + 5 * 60
POWER_POLL_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 10 * 60


def observe_server(server: VirtualMachine) -> str:
	"""Read the owning region and record what it reports about this Team's server."""
	client = _client(server)
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
	client = _client(server)
	remote = client.get_vm(server.atlas_vm_id)
	compute, disk = remote.get("compute") or {}, remote.get("disk") or {}
	cpu_millicores = shape["vcpus"] * 1000
	memory_mib = shape["memory_megabytes"]
	disk_mib = shape["disk_gigabytes"] * 1024

	reshaping = (compute.get("cpu_millicores"), compute.get("memory_mib")) != (cpu_millicores, memory_mib)
	if reshaping:
		_wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")
		client.resize(server.atlas_vm_id, cpu_millicores, memory_mib, disk_mib)
	else:
		if disk_mib > (disk.get("size_mib") or 0):
			client.update_disk(server.atlas_vm_id, disk_mib)
		if compute.get("sleep_after_idle_seconds"):
			client.disable_idle_shutdown(server.atlas_vm_id)

	_wait_for_power_state(client, server.atlas_vm_id, "start", "running")
	observe_server(server)


def process_resize(action) -> None:
	"""Apply one durable resize, then re-lock billing after the shape is confirmed."""
	server = frappe.get_doc("Virtual Machine", action.server, for_update=True)
	if (
		server.team != action.team
		or server.region != action.region
		or server.atlas_vm_id != action.remote_vm_id
	):
		action.transition(
			"Failed", envelope=build_envelope("SERVER_NOT_FOUND", resource_id=action.resource_id)
		)
		return

	first_dispatch = action.status == "Queued"
	if first_dispatch:
		if not can(action.requested_by, action.team, "server:resize", server=action.server):
			action.transition("Failed", envelope=build_envelope("PERMISSION_DENIED", action="resize"))
			return
		action.transition("Dispatching", notify=False)
		action.db_set("dispatched_at", frappe.utils.now_datetime())
		frappe.db.commit()

	configuration = action.get_resize_configuration()
	target = configuration.shape.model_dump()
	try:
		if not first_dispatch:
			observe_server(server)
			server.reload()
		if not _matches_shape(server, target):
			resize_server(server, target)
			server.reload()
		if not _matches_shape(server, target):
			raise AtlasConnectionError(_("Atlas did not report the requested server size."))
	except AtlasRejected as error:
		action.transition(
			"Failed",
			envelope=to_error_response(error),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas resize was rejected",
		)
		return
	except AtlasConnectionError:
		action.transition(
			"Uncertain",
			envelope=build_envelope("OUTCOME_UNKNOWN"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas resize result was uncertain",
		)
		return

	action.transition("Sent", notify=False)
	frappe.db.commit()
	try:
		from central.billing.catalog.subscriptions import apply_resize_billing

		apply_resize_billing(action)
		server.db_set("plan", configuration.plan, notify=False)
	except Exception:
		diagnostic = frappe.get_traceback()
		frappe.db.rollback()
		action.reload()
		action.transition(
			"Sent",
			envelope=build_envelope("FINALIZATION_FAILED"),
			diagnostic=diagnostic,
			diagnostic_title="Resize billing finalization failed",
		)
		return

	action.transition("Succeeded")


def _matches_shape(server: VirtualMachine, shape: dict) -> bool:
	return all(
		frappe.utils.flt(server.get(field)) == frappe.utils.flt(value) for field, value in shape.items()
	)


def _wait_for_power_state(client: AtlasClient, vm_id: str, action: str, state: str) -> None:
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


def process_command(action) -> None:
	server = frappe.get_doc("Virtual Machine", action.server, for_update=True)
	if (
		server.team != action.team
		or server.region != action.region
		or server.atlas_vm_id != action.remote_vm_id
	):
		action.transition(
			"Failed", envelope=build_envelope("SERVER_NOT_FOUND", resource_id=action.resource_id)
		)
		return

	if action.status == "Queued":
		capability = ACTION_CAPABILITIES[action.action]
		if not can(action.requested_by, action.team, capability, server=action.server) or (
			action.take_snapshot
			and not can(action.requested_by, action.team, "server:snapshot", server=action.server)
		):
			action.transition("Failed", envelope=build_envelope("PERMISSION_DENIED", action=action.action))
			return

		client = _client(server)
		if action.take_snapshot and not is_final_snapshot_ready(action, server, client):
			return

		action.transition("Dispatching", notify=False)
		action.db_set("dispatched_at", frappe.utils.now_datetime())
		# The remote command can outlive this worker; recovery must never redispatch it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persist dispatch before Atlas mutates the VM
		try:
			client.vm_action(action.remote_vm_id, action.action)
		except AtlasRequestUncertain as error:
			action.transition(
				"Uncertain",
				envelope=to_error_response(error),
				diagnostic=frappe.get_traceback(),
				diagnostic_title="Atlas command result was uncertain",
			)
		except AtlasResourceGone as error:
			if action.action != "terminate":
				action.transition(
					"Failed",
					envelope=to_error_response(error),
					diagnostic=frappe.get_traceback(),
					diagnostic_title="Atlas resource was not found",
				)
				return
			mark_terminated(server)
			action.record_diagnostic(
				frappe.get_traceback(),
				"Atlas confirmed the terminated resource was gone",
			)
			action.transition("Succeeded")
			return
		except AtlasConnectionError as error:
			action.transition(
				"Failed",
				envelope=to_error_response(error),
				diagnostic=frappe.get_traceback(),
				diagnostic_title="Atlas command failed",
			)
			return
		else:
			action.transition("Sent", notify=False)

		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persist Atlas acceptance before observation

	try:
		status = observe_server(server)
	except AtlasConnectionError:
		action.transition(
			action.status,
			envelope=build_envelope("REFRESH_FAILED"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas server refresh failed",
		)
		return

	action.reload()
	if action.status in TERMINAL_STATES:
		return
	if action.record_observed_status(status):
		return
	if status in ("Failed", "Terminated"):
		action.transition("Failed", envelope=build_envelope("ACTION_FAILED", action=action.action))
	elif _is_command_overdue(action):
		action.transition("Timed Out", envelope=build_envelope("ACTION_TIMED_OUT", action=action.action))
	elif action.action in ROUND_TRIP_ACTIONS:
		return
	else:
		action.transition("In Progress", notify=False)


def is_final_snapshot_ready(action, server: VirtualMachine, client: AtlasClient) -> bool:
	"""Stop the server, take its final snapshot, and return True once it is Available.

	The action stays Queued meanwhile, so the recovery loop runs it again until the snapshot
	settles. A failed snapshot fails the terminate and leaves the server stopped."""
	if action.vm_snapshot:
		status = frappe.db.get_value("VM Snapshot", action.vm_snapshot, "status")
		if status == "Available":
			return True
		if status == "Pending":
			action.db_set("last_checked_at", frappe.utils.now_datetime())
		else:
			action.transition("Failed", envelope=build_envelope("SNAPSHOT_FAILED", action="terminate"))
		return False

	# One snapshot runs per server; a daily one already running is waited out first.
	if frappe.db.exists("VM Snapshot", {"server": server.name, "status": "Pending"}):
		action.db_set("last_checked_at", frappe.utils.now_datetime())
		return False

	try:
		_wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")
	except AtlasConnectionError as error:
		action.transition(
			"Failed",
			envelope=to_error_response(error),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas snapshot preparation failed",
		)
		return False

	snapshot = frappe.get_doc(
		{
			"doctype": "VM Snapshot",
			"title": _("Final snapshot of {0}").format(server.title or server.name),
			"team": server.team,
			"server": server.name,
			"snapshot_type": "Terminate",
			"requested_by": action.requested_by,
		}
	)
	# The terminate already checked server:snapshot for the requester.
	snapshot.insert(ignore_permissions=True)
	action.db_set({"vm_snapshot": snapshot.name, "last_checked_at": frappe.utils.now_datetime()})
	return False


def _is_command_overdue(action) -> bool:
	started = action.dispatched_at or action.creation
	return frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), started) > COMMAND_TIMEOUT_SECONDS


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

	return _client(server).get_console_url(server.atlas_vm_id, mode="ssh")


def refresh_server(name: str) -> None:
	server = frappe.get_doc("Virtual Machine", name, for_update=True)
	if server.status != "Terminated":
		observe_server(server)


def _client(server: VirtualMachine) -> AtlasClient:
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
