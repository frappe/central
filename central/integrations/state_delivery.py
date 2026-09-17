from __future__ import annotations

import base64
import hashlib
import hmac
from typing import NoReturn

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

from central.central.doctype.asset.asset import Asset
from central.central.doctype.resource_action.resource_action import ResourceAction
from central.integrations.servers import mark_terminated

# Central's own clock orders every report, because a report carries the region's clock
# and a scoped read carries Central's. Ordering by the report would let clock skew
# between the two silently suppress events. `observed_at` therefore stays diagnostic:
# what Central records is when it heard, and a repeat is caught by the state itself.

# What a region calls a state, and what Central records for it. A report carrying
# anything else is ignored: Central never invents a status it was not told.
STATUS_FROM_REPORT = {"running": "Running", "stopped": "Stopped", "paused": "Paused"}

STATE_REPORTED = "vm.state"
SERVER_GONE = "vm.gone"


def accept(raw_body: bytes, region: str | None, signature: str | None) -> dict:
	"""Authenticate one delivery, then queue it when it tells Central something new.

	The reply is the sender's receipt: `queued` when a job will apply the report, and
	`ignored` with a reason when there is nothing to do. Only an authentication failure
	raises, because only that is worth a retry."""
	cluster = _verified_cluster(region, signature, raw_body)

	report = _parsed(raw_body)
	if report is None:
		return _ignored("unreadable body")

	server = _server_for(cluster, report.get("virtual_machine"))
	if not server:
		return _ignored("unknown server")

	decision = _decide(report, server)
	if decision:
		return decision

	frappe.enqueue(
		"central.integrations.state_delivery.apply_report",
		queue="short",
		cluster=cluster,
		report=report,
	)
	return {"queued": True, "resource_id": server.name}


def apply_report(cluster: str, report: dict) -> None:
	"""Record one authenticated report. The handler already found it worth applying;
	this repeats the checks under a row lock, because another worker may have applied a
	newer report in between."""
	server = _server_for(cluster, report.get("virtual_machine"))
	if not server:
		return

	if report.get("event") == SERVER_GONE:
		_record_gone(server.name)
		return

	status = STATUS_FROM_REPORT[report["status"]]
	if not Asset.record_observed_state(server.name, frappe.utils.now_datetime(), {"status": status}):
		return

	ResourceAction.confirm_observed_status(server.name, status)


def _decide(report: dict, server: frappe._dict) -> dict | None:
	"""Return the reply for a report Central will not queue, or None to queue it."""
	event = report.get("event")
	if event == SERVER_GONE:
		# Termination is final, so there is no staleness or change to weigh.
		return None if server.status != "Terminated" else _ignored("already terminated")
	if event != STATE_REPORTED:
		return _ignored(f"unsupported event '{event}'")

	status = STATUS_FROM_REPORT.get(report.get("status"))
	if not status:
		return _ignored(f"unsupported status '{report.get('status')}'")
	if server.status == status:
		# Two cases in one: the region reports on a timer rather than on change, and a
		# retried delivery repeats a state Central already recorded. Neither moves
		# anything, so nothing is written and no console is woken.
		return _ignored("no change")

	return None


def _record_gone(resource_id: str) -> None:
	"""A deleted VM ends its server record, its pilot credentials, and its billing."""
	mark_terminated(frappe.get_doc("Asset", resource_id))
	ResourceAction.confirm_observed_status(resource_id, "Terminated")


def _parsed(raw_body: bytes) -> dict | None:
	"""The report as an object, or None when the body is not one."""
	try:
		report = frappe.parse_json(raw_body.decode() or "{}")
	except UnicodeDecodeError:
		return None

	return report if isinstance(report, dict) else None


def _server_for(cluster: str, virtual_machine: str | None) -> frappe._dict | None:
	"""The server record this report is about. Ownership comes from Central's own row,
	never from the report, and the region that signed the delivery scopes the lookup."""
	if not virtual_machine or not isinstance(virtual_machine, str):
		return None

	return frappe.db.get_value(
		"Asset",
		{"cluster": cluster, "atlas_vm_id": virtual_machine},
		["name", "status"],
		as_dict=True,
	)


def _verified_cluster(region: str | None, signature: str | None, raw_body: bytes) -> str:
	"""The region whose secret signed this delivery. `X-Atlas-Region` only selects which
	secret to check; it proves nothing on its own."""
	if not region or not signature:
		_reject("missing region or signature header")
	if frappe.db.get_value("Atlas Instance", region, "status") in (None, "Disabled"):
		_reject(f"unknown or disabled region '{region}'")

	secret = get_decrypted_password("Atlas Instance", region, "webhook_secret", raise_exception=False)
	if not secret:
		_reject(f"no webhook secret for region '{region}'")
	if not _signature_matches(secret, raw_body, signature):
		_reject(f"signature mismatch for region '{region}'")

	return region


def _signature_matches(secret: str, raw_body: bytes, signature: str) -> bool:
	"""Frappe's Webhook signs the exact bytes it sends: base64 of an HMAC-SHA256."""
	expected = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest())
	# Bytes, not str: compare_digest raises TypeError on a non-ASCII string.
	return hmac.compare_digest(expected, signature.encode())


def _reject(reason: str) -> NoReturn:
	"""Log which check failed, for an operator reading repeated rejections, and answer
	every caller with the same sentence so none of them can probe for the reason."""
	frappe.log_error(title="Rejected regional state report", message=reason)

	frappe.throw(_("Invalid signature."), frappe.PermissionError)


def _ignored(reason: str) -> dict:
	return {"queued": False, "ignored": reason}
