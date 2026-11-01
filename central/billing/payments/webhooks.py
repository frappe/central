# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Signature-first webhook receiver.

Verifies the gateway HMAC as the FIRST operation on payload content — before
any content-keyed DB lookup or write — closing the v1 order-ID enumeration bug.
No gateway SDK is imported here; verification/parsing go through the adapter.
No business logic runs in the request cycle: a verified, deduped event is
stored and a background job is enqueued.
"""

import frappe
from frappe import _

from central.billing.platform.records import save_billing_record

# A failed event is retried hourly until it has failed this many times; then it waits for
# an operator, whom the failed-webhook alert has been paging since the first failure.
MAX_TRIES = 5
# A Received event older than this lost its job (a worker restart), so the sweep runs it.
STALE_RECEIVED_MINUTES = 15
RETRY_BATCH = 200

# Events that finish (or fail) a refund the gateway accepted as pending.
REFUND_EVENTS = ("charge.refund.updated", "refund.failed", "refund.processed", "PAYMENT.CAPTURE.REFUNDED")


@frappe.whitelist(allow_guest=True)
def stripe() -> dict:
	return process_webhook(
		"Stripe",
		frappe.request.get_data(),
		dict(frappe.request.headers),
	)


@frappe.whitelist(allow_guest=True)
def razorpay() -> dict:
	return process_webhook(
		"Razorpay",
		frappe.request.get_data(),
		dict(frappe.request.headers),
	)


# nosemgrep: guest-whitelisted-method -- process_webhook verifies PayPal's signature before anything else.
@frappe.whitelist(allow_guest=True)
def paypal() -> dict:
	return process_webhook(
		"Paypal",
		frappe.request.get_data(),
		dict(frappe.request.headers),
	)


def process_webhook(adapter_key: str, payload: bytes, headers: dict) -> dict:
	gateway = _resolve_gateway(adapter_key)
	adapter = gateway.get_adapter()

	# Security gate: nothing keyed on payload content runs until this passes.
	if not adapter.verify_webhook_signature(payload, headers):
		frappe.local.response.http_status_code = 400
		return {"ok": False}

	body = payload.decode() if isinstance(payload, bytes) else payload
	event = adapter.parse_webhook_event(frappe.parse_json(body), headers)
	_store_and_enqueue(gateway, event, payload)
	frappe.local.response.http_status_code = 200
	return {"ok": True, "event": event.gateway_event_id}


def _resolve_gateway(adapter_key: str):
	"""The gateway row this callback URL belongs to.

	There is one callback URL per adapter, so the adapter is the only thing an
	inbound request identifies itself by — which is exactly why a gateway row is
	named after its adapter. The lookup is a primary-key read: no ambiguity about
	which webhook_secret verifies the signature.
	"""
	if not frappe.db.get_value("Payment Gateway", adapter_key, "is_enabled"):
		frappe.throw(_("No enabled Payment Gateway for adapter '{0}'").format(adapter_key))
	return frappe.get_doc("Payment Gateway", adapter_key)


def _store_and_enqueue(gateway, event, payload: bytes):
	"""Idempotent store keyed on gateway_event_id; replays no-op (no second job).

	The unique constraint on gateway_event_id is the real guard: under a
	concurrent flood two requests can both pass the exists() check, so the losing
	insert is caught (DuplicateEntryError) and treated as an already-stored
	replay — exactly one row, exactly one enqueued job.
	"""
	if frappe.db.exists("Webhook Event", {"gateway_event_id": event.gateway_event_id}):
		return

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Webhook Event",
				"gateway": gateway.name,
				"gateway_event_id": event.gateway_event_id,
				"event_type": event.event_type,
				"raw_payload": payload.decode() if isinstance(payload, bytes) else payload,
				"status": "Received",
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return  # lost the race — another request stored it first

	_enqueue_event(doc.name)


def _enqueue_event(event_name: str) -> None:
	"""Apply the event in its own job; the job commits what it did, or its Failed mark.
	The job id keeps a second job for the same event out while one is queued or running."""
	frappe.enqueue(
		"central.billing.payments.webhooks.handle_webhook_event",
		event_name=event_name,
		job_id=f"webhook_event::{event_name}",
		deduplicate=True,
		enqueue_after_commit=True,
	)


def handle_webhook_event(event_name: str):
	"""Apply one stored Webhook Event, and keep it visible if that fails.

	A handler that raises leaves nothing half-written: its work is rolled back, the
	event is marked Failed with the error, and `retry_failed_webhooks` tries it again.
	`platform.alerts.failed_webhooks` pages an operator while it stays Failed. It runs as
	a background job, which commits the Failed mark because this returns normally.

	A slow job and the retry sweep can reach the same event. The row lock makes the
	second wait, and it then finds the event already applied."""
	status = frappe.db.get_value("Webhook Event", event_name, "status", for_update=True)
	if status not in ("Received", "Failed"):
		return {"handled": False, "reason": "already_applied"}

	save_point = "apply_webhook_event"
	frappe.db.savepoint(save_point)
	try:
		return _dispatch(event_name)
	except Exception:
		frappe.db.rollback(save_point=save_point)
		_mark_failed(event_name, frappe.get_traceback())
		frappe.log_error(
			title=f"Webhook Event {event_name} failed",
			reference_doctype="Webhook Event",
			reference_name=event_name,
		)


def _dispatch(event_name: str):
	"""Charge settlement (Open -> Paid) lives in charges.apply_webhook, mandate
	lifecycle in mandates.apply_mandate_event, and card events in
	payments.apply_payment_method_event."""
	from central.billing.payments import charges, corrections, mandates, payments

	event_type = frappe.db.get_value("Webhook Event", event_name, "event_type") or ""
	if event_type in REFUND_EVENTS:
		return corrections.apply_refund_event(event_name)
	if event_type.startswith("mandate."):
		return mandates.apply_mandate_event(event_name)
	if event_type.startswith(("payment_method.", "setup_intent.")):
		return payments.apply_payment_method_event(event_name)
	return charges.apply_webhook(event_name)


def _mark_failed(event_name: str, error: str) -> None:
	from central.billing.states import transition

	event = frappe.get_doc("Webhook Event", event_name)
	if event.status == "Received":
		transition(event, "Failed", actor="webhook", correlation=event.gateway_event_id)
	event.error = error[-2000:]
	event.retry_count = (event.retry_count or 0) + 1
	save_billing_record(event)


def retry_failed_webhooks() -> list[str]:
	"""Hourly: apply again the events that failed, and the ones whose job never ran.

	Each event runs in its own job, so one that fails again does not stop the rest."""
	stale = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-STALE_RECEIVED_MINUTES)
	names = frappe.get_all(
		"Webhook Event",
		filters={"status": "Failed", "retry_count": ["<", MAX_TRIES]},
		pluck="name",
		order_by="creation asc",
		limit=RETRY_BATCH,
	) + frappe.get_all(
		"Webhook Event",
		filters={"status": "Received", "creation": ["<", stale]},
		pluck="name",
		order_by="creation asc",
		limit=RETRY_BATCH,
	)
	for name in names:
		_enqueue_event(name)
	return names
