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


@frappe.whitelist(allow_guest=True)
def stripe() -> dict:
	return process_webhook(
		"stripe",
		frappe.request.get_data(),
		dict(frappe.request.headers),
	)


@frappe.whitelist(allow_guest=True)
def razorpay() -> dict:
	return process_webhook(
		"razorpay",
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
	name = frappe.db.get_value(
		"Payment Gateway", {"adapter_key": adapter_key, "is_enabled": 1}, "name"
	)
	if not name:
		frappe.throw(f"No enabled Payment Gateway for adapter '{adapter_key}'")
	return frappe.get_doc("Payment Gateway", name)


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
				"status": "received",
			}
		).insert(ignore_permissions=True)
	except frappe.DuplicateEntryError:
		return  # lost the race — another request stored it first

	frappe.enqueue(
		"central.billing.payments.webhooks.handle_webhook_event",
		event_name=doc.name,
		enqueue_after_commit=True,
	)


def handle_webhook_event(event_name: str):
	"""Background state transition for a stored Webhook Event.

	Charge settlement (Open -> Paid) lives in charges.apply_webhook; this is the
	dispatch point. Other event families are added as their issues land.
	"""
	from central.billing.payments import charges

	return charges.apply_webhook(event_name)
