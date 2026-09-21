from __future__ import annotations

import base64
import hashlib
import hmac
from typing import NoReturn

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

from central.infrastructure.doctype.resource_action.resource_action import ResourceAction
from central.infrastructure.doctype.virtual_machine.virtual_machine import VirtualMachine
from central.services.doctype.service_detail.service_detail import ServiceDetail

# Central's own clock orders every report, because a report carries the region's clock
# and a scoped read carries Central's. Ordering by the report would let clock skew
# between the two silently suppress events. `observed_at` therefore stays diagnostic:
# what Central records is when it heard, and a repeat is caught by the state itself.

# What a region calls a state, and what Central records for it. A report carrying
# anything else is ignored: Central never invents a status it was not told.
STATUS_FROM_REPORT = {"running": "Running", "stopped": "Stopped", "paused": "Paused"}

STATE_REPORTED = "vm.state"

# What a region may report about itself. Central records these two words and no others.
SERVICES = ("telemetry", "storage")
AVAILABILITY = ("Available", "Not Available")


def accept_atlas_report(raw_body: bytes, region: str | None, signature: str | None) -> dict:
	"""Authenticate one Atlas delivery, then queue it when it tells Central something new.

	The reply is the sender's receipt: `queued` when a job will apply the report, and
	`ignored` with a reason when there is nothing to do. Only an authentication failure
	raises, because only that is worth a retry."""
	cluster = _verified_atlas_cluster(region, signature, raw_body)

	report = _parsed(raw_body)
	if report is None:
		return _ignored("unreadable body")

	server = _atlas_server_for(cluster, report.get("virtual_machine"))
	if not server:
		return _ignored("unknown server")

	decision = _decide(report, server)
	if decision:
		return decision

	frappe.enqueue(
		"central.integrations.state_delivery.apply_atlas_report",
		queue="short",
		cluster=cluster,
		report=report,
	)
	return {"queued": True, "resource_id": server.name}


def accept_cargo_report(raw_body: bytes, region: str | None, signature: str | None) -> dict:
	"""Record what one region now serves, from a delivery its own secret signed. A repeat
	still refreshes `last_updated_on`, which reads as "heard from", not as churn."""
	cargo = _verified_cargo_region(region, signature, raw_body)

	report = _parsed(raw_body)
	if report is None:
		return _ignored("unreadable body")

	service = report.get("service")
	if service not in SERVICES:
		return _ignored(f"unsupported service '{service}'")

	status = report.get("status")
	if status not in AVAILABILITY:
		return _ignored(f"unsupported status '{status}'")

	detail = ServiceDetail.record_report(cargo, service, status, report.get("service_endpoint"))
	return {"recorded": True, "service_detail": detail}


def apply_atlas_report(cluster: str, report: dict) -> None:
	"""Record one authenticated report. The handler already found it worth applying;
	this repeats the checks under a row lock, because another worker may have applied a
	newer report in between."""
	server = _atlas_server_for(cluster, report.get("virtual_machine"))
	if not server:
		return

	status = STATUS_FROM_REPORT[report["status"]]
	if not VirtualMachine.record_observed_state(server.name, frappe.utils.now_datetime(), {"status": status}):
		return

	ResourceAction.confirm_observed_status(server.name, status)
	if status == "Running":
		frappe.enqueue(
			"central.integrations.servers.refresh_server",
			name=server.name,
			enqueue_after_commit=True,
			job_id=f"server-refresh:{server.name}",
			deduplicate=True,
		)


def _decide(report: dict, server: frappe._dict) -> dict | None:
	"""Return the reply for a report Central will not queue, or None to queue it."""
	event = report.get("event")
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


def _parsed(raw_body: bytes) -> dict | None:
	"""The report as an object, or None when the body is not one."""
	try:
		report = frappe.parse_json(raw_body.decode() or "{}")
	except UnicodeDecodeError:
		return None

	return report if isinstance(report, dict) else None


def _atlas_server_for(cluster: str, virtual_machine: str | None) -> frappe._dict | None:
	"""The server record this report is about. Ownership comes from Central's own row,
	never from the report, and the region that signed the delivery scopes the lookup."""
	if not virtual_machine or not isinstance(virtual_machine, str):
		return None

	return frappe.db.get_value(
		"Virtual Machine",
		{"cluster": cluster, "atlas_vm_id": virtual_machine},
		["name", "status"],
		as_dict=True,
	)


def _verified_atlas_cluster(region: str | None, signature: str | None, raw_body: bytes) -> str:
	"""The region whose Atlas secret signed this delivery. `X-FC-Region` only selects which
	secret to check; it proves nothing on its own."""
	if not region or not signature:
		_reject("missing region or signature header")
	if frappe.db.get_value("Region", region, "status") in (None, "Disabled"):
		_reject(f"unknown or disabled region '{region}'")

	secret = get_decrypted_password("Region", region, "webhook_secret", raise_exception=False)
	if not secret:
		_reject(f"no webhook secret for region '{region}'")
	if not _signature_matches(secret, raw_body, signature):
		_reject(f"signature mismatch for region '{region}'")

	return region


def _verified_cargo_region(region: str | None, signature: str | None, raw_body: bytes) -> str:
	"""The region whose Cargo secret signed this delivery. `X-FC-Region` only selects the
	secret; it proves nothing."""
	if not region or not signature:
		_reject("missing region or signature header")

	if frappe.db.get_value("Region", region, "cargo_status") != "Registered":
		_reject(f"unknown or unregistered Cargo region '{region}'")

	secret = get_decrypted_password("Region", region, "cargo_webhook_secret", raise_exception=False)
	if not secret:
		_reject(f"no webhook secret for Cargo region '{region}'")
	if not _signature_matches(secret, raw_body, signature):
		_reject(f"signature mismatch for Cargo region '{region}'")

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
