# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Central -> Agent synchronisation.

Central pushes plan definitions plus a display price to each regional Agent's
Plan Cache. The communication surface is intentionally tiny; this module owns
the Central side of the plan push.
"""

import frappe
import requests

RECEIVE_PLANS_PATH = "/api/method/press_billing_agent.sync.receive_plans"


def _agent_auth_headers() -> dict:
	"""Authorization header for the cluster-scoped Agent API key.

	Credentials live in site config (agent_api_key / agent_api_secret) and are
	never exposed through any customer or admin API.
	"""
	key = frappe.conf.get("agent_api_key")
	secret = frappe.conf.get("agent_api_secret")
	if key and secret:
		return {"Authorization": f"token {key}:{secret}"}
	return {}


@frappe.whitelist()
def push_plans_to_agent(agent_url: str, plans: list | str) -> dict:
	"""Push plan identity + composition + display price to an Agent's Plan Cache.

	Cheap and rare (few clusters). The Agent stores these display-only; it
	computes nothing with them.
	"""
	if isinstance(plans, str):
		plans = frappe.parse_json(plans)

	payload = [frappe.get_doc("Plan", name).as_pricing() for name in plans]

	url = agent_url.rstrip("/") + RECEIVE_PLANS_PATH
	response = requests.post(
		url=url,
		json={"plans": payload},
		headers=_agent_auth_headers(),
		timeout=30,
	)
	response.raise_for_status()
	return response.json().get("message")


@frappe.whitelist()
def receive_usage_events(events: list | str) -> dict:
	"""Agent -> Central: ingest reported plan-change events into the lock ledger.

	Each event carries a stable `event_id`; locking is idempotent on it, so the
	Agent can safely re-push. Only acknowledged event_ids are returned — the
	Agent marks exactly those `synced_to_central`, so a partial failure is
	retried on the next push rather than silently dropped.
	"""
	from central.billing.revenue.pricelock import lock_from_event

	if isinstance(events, str):
		events = frappe.parse_json(events)

	acknowledged = []
	for event in events:
		event_id = lock_from_event(event)
		if event_id:
			acknowledged.append(event_id)

	return {"acknowledged": acknowledged}


@frappe.whitelist()
def receive_meter_rollups(meters: list | str) -> dict:
	"""Agent -> Central: ingest metered rollups into the bounded rollup store.

	Idempotent on each rollup's idempotency_key; a re-push replaces the period
	figure rather than adding. Returns the acknowledged keys so the Agent marks
	exactly those synced.
	"""
	from central.billing.revenue.metering import ingest_rollup

	if isinstance(meters, str):
		meters = frappe.parse_json(meters)

	acknowledged = []
	for meter in meters:
		key = ingest_rollup(meter)
		if key:
			acknowledged.append(key)

	return {"acknowledged": acknowledged}
