# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central price-lock ledger (grandfathering).

When the Agent reports that a resource was provisioned, Central writes an
append-only lock keyed by `resource_id` capturing the **rate the customer was
shown** (`shown_rate`). Billing reads that lock forever; live catalog rate
changes never alter an existing lock. If the shown rate differs from Central's
currently-resolved rate, the lock is written anyway and the divergence recorded
as a discrepancy — the rate shown is the rate honoured.
"""

import frappe


def _open_lock(resource_id: str):
	"""The active lock for a resource (ended_at is null), if any."""
	names = frappe.get_all(
		"Price Lock",
		filters={"resource_id": resource_id, "ended_at": ["is", "not set"]},
		order_by="creation desc",
		pluck="name",
	)
	return names[0] if names else None


def _central_rate(plan: str, currency: str, cluster: str | None):
	"""Central's currently-resolved live rate for the event's plan, or None."""
	if not plan or not frappe.db.exists("Plan", plan):
		return None
	return frappe.get_doc("Plan", plan).get_rate(currency, cluster)


def lock_from_event(event: dict) -> str | None:
	"""Idempotently apply one Agent event to the lock ledger.

	Returns the event_id once handled (so the caller can acknowledge it). A
	repeated push of an already-locked event is a no-op and is simply
	re-acknowledged — the `source_event_id` unique constraint is the idempotency
	key.
	"""
	event_id = event.get("event_id")
	if not event_id:
		return None
	if frappe.db.exists("Price Lock", {"source_event_id": event_id}):
		return event_id  # already processed — re-ack

	resource_id = event["resource_id"]
	event_type = event.get("event_type")
	effective = event.get("effective_from")

	# A plan change or cancellation closes the resource's current open lock.
	if event_type in ("changed", "cancelled"):
		prior = _open_lock(resource_id)
		if prior:
			frappe.db.set_value("Price Lock", prior, "ended_at", event.get("effective_to") or effective)

	shown_rate = event.get("shown_rate")
	currency = event.get("currency")
	cluster = event.get("cluster")
	central_rate = _central_rate(event.get("plan"), currency, cluster)

	discrepancy = central_rate is not None and shown_rate != central_rate
	note = (
		f"Shown rate {shown_rate} {currency} != Central rate {central_rate} "
		f"for {event.get('plan')} @ {cluster or 'global'}"
		if discrepancy
		else None
	)

	frappe.get_doc(
		{
			"doctype": "Price Lock",
			"resource_id": resource_id,
			"team": event.get("team"),
			"plan": event.get("plan"),
			"currency": currency,
			"locked_rate": shown_rate,
			"cluster": cluster,
			"started_at": effective,
			# A cancellation opens no live lock — it is a closed terminal marker.
			"ended_at": (event.get("effective_to") or effective) if event_type == "cancelled" else None,
			"source_event_id": event_id,
			"event_type": event_type,
			"discrepancy": 1 if discrepancy else 0,
			"central_rate": central_rate,
			"discrepancy_note": note,
		}
	).insert(ignore_permissions=True)

	return event_id


def get_locked_rate(resource_id: str):
	"""The rate billing must charge for a resource: its active lock's rate.

	Returns None if the resource has no active lock (never provisioned, or
	cancelled). Live catalog changes never affect this value.
	"""
	lock = _open_lock(resource_id)
	return frappe.db.get_value("Price Lock", lock, "locked_rate") if lock else None
