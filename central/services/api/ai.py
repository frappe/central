from __future__ import annotations

import frappe
from frappe import _

from central.integrations.grove import GroveClient
from central.services import ai
from central.utils.guards import require_capability

VIEW_DENIED = "You can't view this team's AI."
MANAGE_DENIED = "You can't manage this team's AI."
KEY_FIELDS = ("name", "title", "status", "creation", "revocable_at", "masked", "can_read_balance")

# Grove owns the keys. Central keeps none: a secret is shown once, in the answer that mints it.


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_ai(team: str | None = None) -> dict:
	"""Whether AI is on for the team and, when it is, the models it may call and its
	per-minute rate limits."""
	if not ai.get_ai_service(team):
		return {"enabled": False}

	return {"enabled": True, "gateway_url": ai.get_gateway_url(team), **ai.get_overview(team)}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def enable_ai(team: str | None = None) -> dict:
	"""Turn AI on for the team. Safe to repeat."""
	return {"name": ai.enable(team)}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def list_api_keys(team: str | None = None) -> list[dict]:
	"""The team's keys, newest first, masked."""
	require_ai(team)
	keys = GroveClient.from_settings().list_keys(team)
	return [{field: row.get(field) for field in KEY_FIELDS} for row in keys]


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def create_api_key(team: str | None = None, label: str | None = None) -> dict:
	"""Mint a key for the team and return its secret. This is the only time it is shown."""
	require_ai(team)
	label = (label or "").strip()
	if not label:
		frappe.throw(_("A label is required."))

	key = GroveClient.from_settings().provision_key(team, label)
	return {
		"name": key["name"],
		"label": label,
		"gateway_url": key["gateway_url"],
		"api_key": key["api_key"],
	}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def revoke_api_key(team: str | None = None, key: str | None = None) -> dict:
	"""Revoke one of the team's keys. Grove refuses another team's key."""
	require_ai(team)
	GroveClient.from_settings().revoke_key(team, key)
	return {"name": key}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def set_api_key_balance_access(
	team: str | None = None, key: str | None = None, can_read_balance: bool = False
) -> dict:
	"""Let one of the team's keys read the team's credit at the gateway, or stop it. A team's
	first key starts with it."""
	require_ai(team)
	allowed = bool(frappe.utils.sbool(can_read_balance))
	return {"name": key, **GroveClient.from_settings().set_key_balance_access(team, key, allowed)}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_usage(team: str | None = None, period: str = "Last 7 Days", key: str | None = None) -> dict:
	"""What the team used over a period, or through one of its keys: requests and cost, in
	total, per model, and per day."""
	require_ai(team)
	return ai.get_usage_report(team, period, get_key_hash(team, key) if key else None)


@frappe.whitelist(methods=["POST"])
def add_credit(team: str, amount: float, reference: str | None = None) -> dict:
	"""Add USD credit to the team's balance at Grove. Operator only: nothing is charged to the
	team for it. A repeat with the same `reference` adds nothing. Returns the balance after."""
	frappe.only_for("System Manager")
	require_ai(team)
	return GroveClient.from_settings().add_credit(team, amount, reference)


def require_ai(team: str) -> None:
	if not ai.get_ai_service(team):
		frappe.throw(_("AI is not enabled for this team."))


def get_key_hash(team: str, key: str) -> str:
	"""The hash Grove narrows usage by, for one of the team's own keys."""
	for row in GroveClient.from_settings().list_keys(team):
		if row["name"] == key:
			return row["key_hash"]
	frappe.throw(_("Unknown API key."), frappe.DoesNotExistError)
