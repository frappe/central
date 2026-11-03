import json

import frappe

from central.billing.gateways.registry import adapter_class
from central.billing.payments import webhooks

PAGE_SIZE = 500


def execute() -> None:
	"""Remove the Ignored, unlinked events that the live webhook rule says are not Central's.
	Frappe Cloud v1 sent them over the shared gateway accounts."""
	adapters: dict = {}
	last_name = ""
	while page := _next_page(last_name):
		_remove_events_of_another_product(page, adapters)
		last_name = page[-1].name


def _next_page(last_name: str) -> list:
	return frappe.get_all(
		"Webhook Event",
		filters={
			"status": "Ignored",
			"payment_attempt": ["is", "not set"],
			"payment_method": ["is", "not set"],
			"name": [">", last_name],
		},
		fields=["name", "gateway", "raw_payload"],
		order_by="name asc",
		limit=PAGE_SIZE,
	)


def _remove_events_of_another_product(page: list, adapters: dict) -> None:
	names = [event.name for event in page if is_event_of_another_product(event, adapters)]
	if not names:
		return

	frappe.db.delete("Webhook Event", {"name": ["in", names]})
	frappe.db.delete(
		"Billing Event",
		{"event_type": "Webhook Event Ignored", "subject_doctype": "Webhook Event", "subject": ["in", names]},
	)


def is_event_of_another_product(event, adapters: dict) -> bool:
	"""The live rule, `webhooks.is_central_event`, on the stored body. A body the live path could not
	read never reached that rule, so it is kept."""
	adapter = _adapter(event.gateway, adapters)
	payload = _payload(event.raw_payload)
	if adapter is None or payload is None:
		return False
	return not webhooks.is_central_event(adapter, payload)


def _adapter(gateway: str | None, adapters: dict):
	if gateway not in adapters:
		adapter_key = frappe.db.get_value("Payment Gateway", gateway, "adapter_key") if gateway else None
		adapters[gateway] = _adapter_class(adapter_key)
	return adapters[gateway]


def _adapter_class(adapter_key: str | None):
	try:
		return adapter_class(adapter_key)
	except frappe.ValidationError:
		return None


def _payload(raw_payload: str | None) -> dict | None:
	try:
		payload = json.loads(raw_payload or "")
	except ValueError:
		return None
	return payload if isinstance(payload, dict) else None
