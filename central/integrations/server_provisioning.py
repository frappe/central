from __future__ import annotations

import json

import frappe
from frappe import _
from redis.exceptions import LockError

from central.central.doctype.pilot_credential.pilot_credential import PilotCredential
from central.errors import AtlasConnectionError, AtlasRequestUncertain, build_envelope, to_error_response
from central.iam import can
from central.integrations.atlas import AtlasClient
from central.integrations.servers import observe_server
from central.sso import central_url, jwks_url


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
		request.set_error("Uncertain", build_envelope("OUTCOME_UNKNOWN"))
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
	except AtlasRequestUncertain as error:
		request.set_error("Uncertain", to_error_response(error))
		return
	except (AtlasConnectionError, frappe.ValidationError, frappe.PermissionError) as error:
		PilotCredential.revoke_by_id(request.credential)
		request.set_error("Failed", to_error_response(error))
		return

	_finalize(request)


def _client(request) -> AtlasClient:
	instance = frappe.get_doc("Atlas Instance", request.atlas_instance)
	tenant_id = frappe.db.get_value("Team", request.team, "tenant_id")
	return AtlasClient(instance, tenant_id)


def _create_payload(request) -> dict:
	configuration = request.get_configuration()
	payload = {
		"image_id": configuration.image_id,
		"vcpus": configuration.virtual_cpu_count,
		"memory_mib": configuration.memory_mib,
		"disk_mib": configuration.disk_mib,
		"hostname": configuration.hostname or "",
		"ssh_keys": configuration.ssh_keys,
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
			}
		)

	return payload


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
	"""Recover lost queue deliveries and read accepted VMs without repeating a create."""
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-3)
	action = frappe.qb.DocType("Resource Action")
	rows = (
		frappe.qb.from_(action)
		.select(action.name)
		.where(
			(action.modified < cutoff)
			& (
				action.status.isin(("Queued", "Dispatching", "Sent", "In Progress"))
				| (
					(action.status == "Uncertain")
					& action.remote_vm_id.isnotnull()
					& (action.remote_vm_id != "")
				)
			)
		)
		.orderby(action.modified)
		.limit(100)
	).run(as_dict=True)
	for row in rows:
		frappe.get_doc("Resource Action", row.name).enqueue()


def resolve_created_vm(name: str, remote_vm_id: str) -> None:
	"""Bind an unknown create only when Atlas confirms its tenant and action marker."""
	if not isinstance(remote_vm_id, str) or not remote_vm_id:
		frappe.throw(_("Enter an Atlas VM ID."))

	action = frappe.get_doc("Resource Action", name, for_update=True)
	if action.action != "create" or action.status != "Uncertain" or action.remote_vm_id:
		frappe.throw(_("Only an uncertain creation without a VM identity can be resolved."))

	client = _client(action)
	remote = client.get_vm(remote_vm_id)
	configuration = action.get_configuration()
	metadata = remote.get("guest", {}).get("metadata", {})
	if (
		remote.get("tenant_id") != client.tenant_id
		or remote.get("id") != remote_vm_id
		or remote.get("image_id") != configuration.image_id
		or metadata.get("central_action_id") != action.name
	):
		frappe.throw(_("This VM does not match the Team, image and creation action."))

	action.db_set(
		{
			"remote_vm_id": remote_vm_id,
			"status": "Sent",
			"error_code": None,
			"error_message": None,
			"remediation": None,
		}
	)
	action.enqueue()
