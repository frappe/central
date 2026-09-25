from __future__ import annotations

import json

import frappe
from frappe import _
from redis.exceptions import LockError, LockNotOwnedError

from central.api.jwks import jwks_document
from central.errors import AtlasConnectionError, AtlasRequestUncertain, build_envelope
from central.infrastructure.doctype.pilot_credential.pilot_credential import PilotCredential
from central.infrastructure.doctype.resource_action.resource_action import PENDING_STATES, TERMINAL_STATES
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.integrations.atlas import AtlasClient
from central.integrations.bucket_provisioning import BucketProvisioning
from central.integrations.servers import observe_server
from central.sso import central_url, jwks_url

# A region stamps its own clock on a machine, so allow for a little drift when deciding
# which machines are new enough to have come from this request.
CLOCK_SKEW_SECONDS = 120
# Long enough to cover a region answering a create, so the lock outlives the work it
# guards rather than expiring under it.
LOCK_TIMEOUT_SECONDS = 15 * 60
ANYWHERE = ["0.0.0.0/0", "::/0"]
# Atlas addresses every machine on its WireGuard mesh from this prefix, and an enabled
# firewall filters mesh traffic too.
MESH_NETWORK = "fdaa::/16"


def process_request(name: str) -> None:
	"""Dispatch once, then recover accepted creates using reads only."""
	try:
		with frappe.cache.lock(
			f"server-provisioning:{name}", timeout=LOCK_TIMEOUT_SECONDS, blocking_timeout=0
		):
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
		from central.integrations.servers import process_resize

		process_resize(request)
		return

	if request.action != "create":
		from central.integrations.servers import process_command

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
	started = frappe.utils.get_datetime(request.dispatched_at or request.creation).timestamp()

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
		from central.server_provisioning import resolve_team_ssh_keys

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
		credential = f"pilot-{request.name}"
		token = PilotCredential.mint(request.team, credential, audience_id=credential)
		request.db_set("credential", credential)
		bootstrap = {
			"central_endpoint": central_url(),
			"central_auth_token": token,
			"jwks_url": jwks_url(),
			"jwks_audience_id": credential,
			# The keys, delivered with the credential, so the pilot's first token
			# needs no fetch and a boot before Central is reachable still verifies.
			"initial_jwks_cache": jwks_document(),
		}
		try:
			bootstrap["s3"] = BucketProvisioning(request).get_configuration()
		except Exception:
			request.record_diagnostic(
				frappe.get_traceback(),
				"Pilot object storage provisioning failed",
			)
		payload["metadata"]["pilot-central"] = json.dumps(bootstrap)

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
		status = observe_server(frappe.get_doc("Virtual Machine", server_id))
	except AtlasConnectionError:
		request.transition(
			"Sent",
			envelope=build_envelope("REFRESH_FAILED"),
			diagnostic=frappe.get_traceback(),
			diagnostic_title="Atlas server refresh failed",
		)
		return

	request.finish(status)


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
