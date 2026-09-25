from __future__ import annotations

from zoneinfo import ZoneInfo

import frappe
from frappe import _
from redis.exceptions import LockError, LockNotOwnedError

from central.errors import (
	AtlasConnectionError,
	AtlasRejected,
	AtlasRequestUncertain,
	AtlasResourceGone,
	build_envelope,
	to_error_response,
)
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES, TERMINAL_STATES
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations import servers
from central.integrations.atlas import AtlasClient
from central.integrations.pilot import get_bootstrap_metadata

# A region stamps its own clock on a machine, so allow for a little drift when deciding
# which machines are new enough to have come from this request.
CLOCK_SKEW_SECONDS = 120
# How long one dispatch job may run. Its lock lasts as long, so a second worker never
# starts while the first still works. A job waits for at most one power change, such as
# the stop before a final snapshot. A resize waits for a stop and a start.
JOB_TIMEOUT_SECONDS = servers.POWER_WAIT_SECONDS + 5 * 60
RESIZE_JOB_TIMEOUT_SECONDS = 2 * servers.POWER_WAIT_SECONDS + 5 * 60
ANYWHERE = ["0.0.0.0/0", "::/0"]
# Atlas addresses every machine on its WireGuard mesh from this prefix, and an enabled
# firewall filters mesh traffic too.
MESH_NETWORK = "fdaa::/16"


def get_job_timeout_seconds(action: str | None) -> int:
	return RESIZE_JOB_TIMEOUT_SECONDS if action == "resize" else JOB_TIMEOUT_SECONDS


def process_request(name: str) -> None:
	"""Dispatch once, then recover accepted creates using reads only."""
	timeout = get_job_timeout_seconds(frappe.db.get_value("Resource Action", name, "action"))
	try:
		with frappe.cache.lock(f"server-provisioning:{name}", timeout=timeout, blocking_timeout=0):
			try:
				_process_locked(name)
			except Exception:
				# A worker crash must leave an actionable record without repeating a mutation.
				diagnostic = frappe.get_traceback()
				frappe.db.rollback()
				action = frappe.get_doc("Resource Action", name, for_update=True)
				if action.status == "Queued":
					action.transition("Failed", envelope=build_envelope("UNEXPECTED"), diagnostic=diagnostic)
				elif action.action == "resize" and action.status == "Dispatching":
					action.transition(
						"Uncertain", envelope=build_envelope("OUTCOME_UNKNOWN"), diagnostic=diagnostic
					)
				elif action.remote_vm_id:
					action.transition(
						"Sent", envelope=build_envelope("FINALIZATION_FAILED"), diagnostic=diagnostic
					)
				else:
					action.transition(
						"Uncertain", envelope=build_envelope("OUTCOME_UNKNOWN"), diagnostic=diagnostic
					)
	except LockNotOwnedError:
		# Ours expired while the region was still answering. The work ran unguarded and may
		# be half finished, which is not the same as another worker holding the lock, so it
		# is recorded rather than passed over in silence.
		diagnostic = frappe.get_traceback()
		frappe.db.rollback()
		if frappe.db.exists("Resource Action", name):
			frappe.get_doc("Resource Action", name).record_diagnostic(
				diagnostic, "Resource action lock expired"
			)
		else:
			frappe.log_error(title=f"Resource action lock expired: {name}", message=diagnostic)
	except LockError:
		# Another worker holds it. Theirs to finish.
		return


def _process_locked(name: str) -> None:
	request = frappe.get_doc("Resource Action", name, for_update=True)
	if request.status in TERMINAL_STATES:
		return

	if request.action == "resize":
		process_resize(request)
		return

	if request.action != "create":
		process_command(request)
		return

	if request.remote_vm_id:
		_finalize(request)
		return

	if request.status != "Queued":
		recover_unanswered(request)
		return

	try:
		if not request.is_allowed():
			frappe.throw(
				_("The requester no longer has permission to create this server."), frappe.PermissionError
			)

		if frappe.db.get_value("Region", request.region, "status") != "Active":
			frappe.throw(_("This region is not accepting server creation."))
		client = _client(request)
		payload = _create_payload(request)
		request.transition("Dispatching", notify=False)
		# Persist the dispatch marker and credential before a remote mutation can succeed.
		try:
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			raise
		response = client.create_vm(payload)
		remote_id = response.get("id")
		if not isinstance(remote_id, str) or not remote_id or response.get("tenant_id") != client.tenant_id:
			raise AtlasRequestUncertain(
				_("Atlas returned an invalid creation receipt. An operator must check the result.")
			)

		request.db_set("remote_vm_id", remote_id)
		request.transition("Sent", notify=False)
		# Retain the remote identity even if local billing or mirror finalization fails.
		frappe.db.commit()
	except AtlasRequestUncertain:
		request.record_diagnostic(frappe.get_traceback(), "Atlas create result was uncertain")
		recover_unanswered(request)
		return
	except (AtlasConnectionError, frappe.ValidationError, frappe.PermissionError) as error:
		request.fail(error, "Atlas create failed")
		return

	_finalize(request)


def recover_unanswered(request) -> None:
	"""Settle a creation the region never answered, by asking it what it built.

	Central marks every create with its action ID, so the region can say whether this
	request produced a machine. Finding one binds it and the creation carries on. Only a
	search that completed can say no, and that is a plain failure the customer can send
	again. A region Central cannot reach proves nothing, so the request stays open for
	the next sweep."""
	try:
		remote_vm_id = find_created_vm(request)
	except AtlasConnectionError:
		request.transition(
			"Uncertain",
			envelope=build_envelope("OUTCOME_UNKNOWN"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas create recovery failed",
		)
		return

	if not remote_vm_id:
		request.transition("Failed", envelope=build_envelope("CREATE_NOT_ACCEPTED", action=request.action))
		return

	request.db_set("remote_vm_id", remote_vm_id)
	request.transition("Sent", notify=False)
	frappe.db.commit()
	_finalize(request)


def find_created_vm(request) -> str | None:
	"""The machine this creation built, or None when the region holds none.

	The region lists newest first, so the search stops at the first machine older than
	the dispatch. A candidate counts only when its tenant, image and action marker all
	match, which is what keeps another request's machine from being adopted."""
	client = _client(request)
	configuration = request.get_configuration()
	# Central stores naive times in its system time zone, and `timestamp()` would read them in
	# the process time zone. The region stamps real Unix seconds.
	dispatched = frappe.utils.get_datetime(request.dispatched_at or request.creation)
	started = dispatched.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone())).timestamp()

	for row in client.list_vms():
		created_at = row.get("created_at")
		if not isinstance(created_at, int) or created_at < started - CLOCK_SKEW_SECONDS:
			break
		remote = client.get_vm(row["id"])
		if (
			remote.get("tenant_id") == client.tenant_id
			and remote.get("image_id") == configuration.image_id
			and remote.get("guest", {}).get("metadata", {}).get("central_action_id") == request.name
		):
			return row["id"]

	return None


def _client(request) -> AtlasClient:
	instance = frappe.get_doc("Region", request.region)
	tenant_id = frappe.db.get_value("Team", request.team, "tenant_id")
	return AtlasClient(instance, tenant_id)


def _create_payload(request) -> dict:
	configuration = request.get_configuration()
	if configuration.ssh_key_ids:
		from central.resource_actions import resolve_team_ssh_keys

		configuration.ssh_keys = resolve_team_ssh_keys(request.team, configuration.ssh_key_ids)
	payload = {
		"image_id": configuration.image_id,
		"cpu_millicores": configuration.virtual_cpu_count * 1000,
		"memory_mib": configuration.memory_mib,
		"disk_mib": configuration.disk_mib,
		"hostname": configuration.hostname or "",
		"ssh_keys": configuration.ssh_keys,
		"firewall": firewall_configuration(configuration),
		"sleep_after_idle_seconds": idle_shutdown_seconds(request.team),
		"metadata": {"central_action_id": request.name},
	}
	if configuration.has_public_ipv6:
		payload["public_ipv6"] = "auto"
	if configuration.image_tags.get("purpose") == "pilot":
		payload["metadata"]["pilot-central"] = get_bootstrap_metadata(request)

	return payload


def firewall_configuration(configuration) -> dict:
	"""The Atlas firewall for a new machine. A disabled firewall permits all traffic.

	1. Allow the region's mesh, which the regional gateway and console use.
	2. Allow ICMP, which IPv6 neighbour discovery and path MTU need.
	3. Allow SSH, HTTP, and HTTPS from anywhere.
	4. Allow all outbound traffic."""
	if not configuration.is_firewall_enabled:
		return {"enabled": False}

	return {
		"enabled": True,
		"inbound": [
			{"protocol": "any", "cidrs": [MESH_NETWORK]},
			{"protocol": "icmp", "cidrs": ANYWHERE},
			*({"protocol": "tcp", "ports": port, "cidrs": ANYWHERE} for port in ("22", "80", "443")),
		],
		"outbound": [{"protocol": "any", "cidrs": ANYWHERE}],
	}


def idle_shutdown_seconds(team: str) -> int:
	"""How long a machine may sit idle before its region puts it to sleep.

	Sleep is a hobby comfort: a trial server costs nothing while nobody uses it, and
	customer traffic wakes it. A paid server stays up, and so does every server once its
	owner resizes it."""
	if not frappe.db.get_value("Team", team, "is_staging_trial"):
		return 0

	minutes = frappe.get_cached_value("Central Settings", "Central Settings", "trial_idle_shutdown_minutes")
	return max(0, int(minutes or 0)) * 60


def _finalize(request) -> None:
	try:
		frappe.db.get_value("Team", request.team, "name", for_update=True)
		server_id = request.server or f"server-{request.name}"
		if not request.server:
			from central.billing.catalog.subscriptions import create_server_subscription

			VirtualMachine.create_from_action(request, server_id)
			create_server_subscription(request, server_id)
			PilotCredential.link_server(request.credential, server_id)
			request.db_set({"server": server_id, "resource_id": server_id})
		# Finalize local ownership and billing together, independently of the next remote read.
		frappe.db.commit()
	except Exception:
		diagnostic = frappe.get_traceback()
		frappe.db.rollback()
		request.reload()
		request.transition(
			"Sent",
			envelope=build_envelope("FINALIZATION_FAILED"),
			diagnostic=diagnostic,
			diagnostic_title="Server finalization failed",
		)
		return

	try:
		status = servers.observe_server(frappe.get_doc("Virtual Machine", server_id))
	except AtlasConnectionError:
		request.transition(
			"Sent",
			envelope=build_envelope("REFRESH_FAILED"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas server refresh failed",
		)
		return

	request.finish(status)


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
		if not action.is_allowed():
			action.transition("Failed", envelope=build_envelope("PERMISSION_DENIED", action="resize"))
			return
		action.transition("Dispatching", notify=False)
		frappe.db.commit()

	configuration = action.get_resize_configuration()
	target = configuration.shape.model_dump()
	try:
		if not first_dispatch:
			servers.observe_server(server)
			server.reload()
		if not _matches_shape(server, target):
			servers.resize_server(server, target)
			server.reload()
		if not _matches_shape(server, target):
			raise AtlasConnectionError(_("Atlas did not report the requested server size."))
	except AtlasRejected as error:
		action.fail(error, "Atlas resize was rejected")
		return
	except AtlasConnectionError:
		# A resize sets absolute values, so recovery can safely run it again.
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
		if not action.is_allowed():
			action.transition("Failed", envelope=build_envelope("PERMISSION_DENIED", action=action.action))
			return

		client = servers.get_client(server)
		if action.take_snapshot and not is_final_snapshot_ready(action, server, client):
			return

		action.transition("Dispatching", notify=False)
		# The remote command can outlive this worker; recovery must never redispatch it.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persist dispatch before Atlas mutates the VM
		try:
			client.vm_action(action.remote_vm_id, action.action)
		except AtlasResourceGone as error:
			# A terminate that finds the machine gone has reached its goal.
			if action.action != "terminate":
				action.fail(error, "Atlas command failed")
				return
			servers.mark_terminated(server)
			action.transition("Succeeded")
			return
		except AtlasConnectionError as error:
			action.fail(error, "Atlas command failed")
			# An uncertain reply is settled by the read below, never by a second command.
			if action.status == "Failed":
				return
		else:
			action.transition("Sent", notify=False)

		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- persist Atlas acceptance before observation

	try:
		status = servers.observe_server(server)
	except AtlasConnectionError:
		action.transition(
			action.status,
			envelope=build_envelope("REFRESH_FAILED"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas server refresh failed",
		)
		return

	action.finish(status)


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
		servers.wait_for_power_state(client, server.atlas_vm_id, "stop", "stopped")
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


def recover_requests() -> None:
	"""Recover lost queue deliveries, and settle creations the region never answered.

	Nothing here repeats a create: an accepted machine is read, and an unanswered request
	is looked up by its action marker."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-3)
	action = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(action)
		.select(action.name)
		.where((action.modified < cutoff) & action.status.isin(PENDING_STATES))
		.orderby(action.modified)
		.limit(100)
	).run(as_dict=True)
	for row in rows:
		frappe.get_doc("Resource Action", row.name).enqueue()
