# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Usage recording — Central writes the runtime it bills from.

Agentless (ADR 0006): there is no Subscription Agent and no push/pull sync.
Central provisions and meters via the cluster manager and records what it drives
directly — the event log (subscribed / changed / cancelled, per `resource_id`
with `shown_rate` + currency) into the price-lock ledger, and metered-usage
rollups into the bounded rollup store. These are *internal* recording calls made
by the provisioning/metering paths, not whitelisted endpoints an external party
posts to (which would let any caller forge usage and so a price lock).
"""

import frappe


def record_usage_events(events: list | str) -> dict:
	"""Record provisioning events into the price-lock ledger as Central drives them.

	Each event carries a stable `event_id`; locking is idempotent on it, so a
	replay (e.g. a metering refresh from the cluster manager) is a safe no-op.
	Returns the handled event_ids.
	"""
	from central.billing.revenue.pricelock import lock_from_event

	if isinstance(events, str):
		events = frappe.parse_json(events)

	recorded = []
	for event in events:
		event_id = lock_from_event(event)
		if event_id:
			recorded.append(event_id)

	# `acknowledged` kept alongside `recorded` for back-compat with existing callers.
	return {"recorded": recorded, "acknowledged": recorded}


def record_meter_rollups(meters: list | str) -> dict:
	"""Record metered rollups into the bounded rollup store as Central meters.

	Idempotent on each rollup's idempotency_key; a refresh replaces the period
	figure rather than adding. Returns the handled keys.
	"""
	from central.billing.revenue.metering import ingest_rollup

	if isinstance(meters, str):
		meters = frappe.parse_json(meters)

	recorded = []
	for meter in meters:
		key = ingest_rollup(meter)
		if key:
			recorded.append(key)

	return {"recorded": recorded, "acknowledged": recorded}


# Deprecated agent-era names — kept so existing callers/tests keep working while
# they migrate to record_*. The "Agent → Central push" they implied is gone.
receive_usage_events = record_usage_events
receive_meter_rollups = record_meter_rollups
