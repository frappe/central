from __future__ import annotations

import json

import frappe
from frappe import _
from redis.exceptions import LockError

from central.api.jwks import jwks_document
from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.errors import AtlasConnectionError, AtlasRequestUncertain, build_envelope, to_error_response
from central.iam import can
from central.integrations.atlas import AtlasClient
from central.integrations.servers import observe_server
from central.sso import central_url, jwks_url

# A region stamps its own clock on a machine, so allow for a little drift when deciding
# which machines are new enough to have come from this request.
CLOCK_SKEW_SECONDS = 120


def process_request(name: str) -> None:
	"""Dispatch once, then recover accepted creates using reads only."""
	try:
		with frappe.cache.lock(f"server-provisioning:{name}", timeout=180, blocking_timeout=0):
			try:
				_process_locked(name)
			except Exception:
				# A worker crash must leave an actionable record without repeating a mutation.
				frappe.db.rollback()
				frappe.log_error(
					title="Resource action failed", message=frappe.get_traceback(with_context=False)
				)
				action = frappe.get_doc("Resource Action", name, for_update=True)
				if action.status == "Queued":
					action.set_error("Failed", build_envelope("UNEXPECTED"))
				elif action.remote_vm_id:
					action.set_error("Sent", build_envelope("FINALIZATION_FAILED"))
				else:
					action.set_error("Uncertain", build_envelope("OUTCOME_UNKNOWN"))
	except LockError:
		return


def _process_locked(name: str) -> None:
	request = frappe.get_doc("Resource Action", name, for_update=True)
	if request.status in ("Succeeded", "Failed", "Timed Out"):
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
		if not can(request.requested_by, request.team, "server:create"):
			frappe.throw(
				_("The requester no longer has permission to create this server."), frappe.PermissionError
			)

		if frappe.db.get_value("Atlas Instance", request.atlas_instance, "status") != "Active":
			frappe.throw(_("This region is not accepting server creation."))
		client = _client(request)
		payload = _create_payload(request)
		request.db_set({"status": "Dispatching", "dispatched_at": frappe.utils.now_datetime()})
		# Persist the dispatch marker and credential before a remote mutation can succeed.
		frappe.db.commit()
		response = client.create_vm(payload)
		remote_id = response.get("id")
		if not isinstance(remote_id, str) or not remote_id or response.get("tenant_id") != client.tenant_id:
			raise AtlasRequestUncertain(
				_("Atlas returned an invalid creation receipt. An operator must check the result.")
			)

		request.db_set({"remote_vm_id": remote_id, "status": "Sent", "error_message": None})
		# Retain the remote identity even if local billing or mirror finalization fails.
		frappe.db.commit()
	except AtlasRequestUncertain:
		recover_unanswered(request)
		return
	except (AtlasConnectionError, frappe.ValidationError, frappe.PermissionError) as error:
		PilotCredential.revoke_by_id(request.credential)
		request.set_error("Failed", to_error_response(error))
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
		request.set_error("Uncertain", build_envelope("OUTCOME_UNKNOWN"))
		return

	if not remote_vm_id:
		PilotCredential.revoke_by_id(request.credential)
		request.set_error("Failed", build_envelope("CREATE_NOT_ACCEPTED", action=request.action))
		return

	request.db_set(
		{
			"remote_vm_id": remote_vm_id,
			"status": "Sent",
			"error_code": None,
			"error_message": None,
			"remediation": None,
			"retriable": 0,
		}
	)
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
	instance = frappe.get_doc("Atlas Instance", request.atlas_instance)
	tenant_id = frappe.db.get_value("Team", request.team, "tenant_id")
	return AtlasClient(instance, tenant_id)


def _create_payload(request) -> dict:
	configuration = request.get_configuration()
	payload = {
		"image_id": configuration.image_id,
		"cpu_millicores": configuration.virtual_cpu_count * 1000,
		"memory_mib": configuration.memory_mib,
		"disk_mib": configuration.disk_mib,
		"hostname": configuration.hostname or "",
		"ssh_keys": configuration.ssh_keys,
		"firewall": {"enabled": False},
		"sleep_after_idle_seconds": idle_shutdown_seconds(request.team),
		"metadata": {"central_action_id": request.name},
	}
	if configuration.image_tags.get("purpose") == "pilot":
		credential = f"pilot-{request.name}"
		token = PilotCredential.mint(request.team, credential, audience_id=credential)
		request.db_set("credential", credential)
		payload["metadata"]["pilot-central"] = json.dumps(
			{
				"central_endpoint": central_url(),
				"central_auth_token": token,
				"jwks_url": jwks_url(),
				"jwks_audience_id": credential,
				# The keys, delivered with the credential, so the pilot's first token
				# needs no fetch and a boot before Central is reachable still verifies.
				"initial_jwks_cache": jwks_document(),
			}
		)

	return payload


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
		asset_id = request.asset or f"server-{request.name}"
		if not request.asset:
			_create_asset(request, asset_id)
			_create_subscription(request, asset_id)
			PilotCredential.link_asset(request.credential, asset_id)
			request.db_set({"asset": asset_id, "resource_id": asset_id})
		# Finalize local ownership and billing together, independently of the next remote read.
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Server finalization failed", message=frappe.get_traceback(with_context=False))
		request.reload()
		request.set_error("Sent", build_envelope("FINALIZATION_FAILED"))
		return

	try:
		status = observe_server(frappe.get_doc("Asset", asset_id))
	except AtlasConnectionError:
		request.set_error("Sent", build_envelope("REFRESH_FAILED"))
		return

	if status == "Running":
		request.succeed()
	elif status in ("Failed", "Terminated"):
		request.set_error("Failed", build_envelope("ACTION_FAILED", action="create"))
	else:
		request.db_set(
			{
				"status": "In Progress",
				"last_checked_at": frappe.utils.now_datetime(),
				"error_code": None,
				"error_message": None,
				"remediation": None,
				"retriable": 0,
			}
		)


def _create_asset(request, asset_id: str) -> None:
	"""Open the server record. Central owns every value here; the region only reports
	state afterwards, through `Asset.record_observed_state`.

	Recovery can reach this again after a local failure, so an already-open record is
	left alone. The id comes from the request, so a second attempt carries the same
	values as the first."""
	if frappe.db.exists("Asset", asset_id):
		return

	configuration = request.get_configuration()
	# The authorized request is what permits this write, not the requesting user's role.
	frappe.get_doc(
		{
			"doctype": "Asset",
			"resource_id": asset_id,
			"title": request.title,
			"team": request.team,
			"cluster": request.atlas_instance,
			"status": "Provisioning",
			"atlas_vm_id": request.remote_vm_id,
			"atlas_image_id": configuration.image_id,
			"image_offering": configuration.offering,
			"plan": configuration.plan,
			"vcpus": configuration.virtual_cpu_count,
			"memory_megabytes": configuration.memory_mib,
			"disk_gigabytes": configuration.disk_mib / 1024,
			"frappe_version": configuration.image_tags.get("frappe_version"),
		}
	).insert(ignore_permissions=True)


def _create_subscription(request, asset_id: str) -> None:
	from central.billing.catalog.subscriptions import create_subscription

	configuration = request.get_configuration()
	if frappe.db.exists("Subscription", {"team": request.team, "asset_id": asset_id}):
		return

	# The reservation already passed policy and budget checks before dispatch.
	create_subscription(
		request.team,
		request.atlas_instance,
		plan=configuration.plan,
		billing_cycle=configuration.billing_cycle,
		resource_id=asset_id,
		changed_by=request.requested_by,
		pricing_mode="Preset" if configuration.plan else "Composed",
		includes=None if configuration.plan else [row.model_dump() for row in configuration.includes],
		sub_category=configuration.sub_category,
		opening_quote=(request.reserved_monthly_rate, configuration.currency),
	)


def recover_requests() -> None:
	"""Recover lost queue deliveries, and settle creations the region never answered.

	Nothing here repeats a create: an accepted machine is read, and an unanswered request
	is looked up by its action marker."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-3)
	action = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(action)
		.select(action.name)
		.where(
			(action.modified < cutoff)
			& action.status.isin(("Queued", "Dispatching", "Sent", "In Progress", "Uncertain"))
		)
		.orderby(action.modified)
		.limit(100)
	).run(as_dict=True)
	for row in rows:
		frappe.get_doc("Resource Action", row.name).enqueue()
