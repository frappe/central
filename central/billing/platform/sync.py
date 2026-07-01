# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Usage recording — Central writes the runtime it bills from.

Agentless (ADR 0006): there is no Subscription Agent and no push/pull sync.
Central provisions and meters via the cluster manager and records what it drives
directly. Provisioning opens the billing segment inline (`provision_subscription`
writes the `Created` Subscription Change — the price-lock itself, ADR 0010), so
there is no separate event-log ingestion; metered-usage rollups still land in the
bounded rollup store here. This is an *internal* recording call made by the metering
path, not a whitelisted endpoint an external party posts to (which would let any
caller forge usage).
"""

import frappe


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


# Deprecated agent-era name — kept so existing callers/tests keep working while
# they migrate to record_*. The "Agent → Central push" it implied is gone.
receive_meter_rollups = record_meter_rollups
