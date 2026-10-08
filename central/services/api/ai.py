from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from central.integrations.grove import GroveClient
from central.services import ai
from central.utils.guards import require_capability

VIEW_DENIED = "You can't view this team's AI."
MANAGE_DENIED = "You can't manage this team's AI."
KEY_FIELDS = (
	"name",
	"title",
	"status",
	"creation",
	"revocable_at",
	"masked",
	"geography",
	"gateway_url",
	"cap",
	"spent",
	"limits",
)

# Grove owns the keys. Central keeps none: a secret is shown once, in the answer that mints it.


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_ai(team: str | None = None) -> dict:
	"""Whether AI is on for the team and, when it is, its balance, this month's usage and the
	geographies a key may be minted in."""
	if not ai.get_ai_service(team):
		return {"enabled": False}

	return {"enabled": True, **ai.get_overview(team)}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def enable_ai(team: str | None = None) -> dict:
	"""Turn AI on for the team. Safe to repeat."""
	return {"name": ai.enable(team)}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def list_api_keys(team: str | None = None) -> list[dict]:
	"""The team's keys, newest first, masked, each with its geography and the gateway it
	calls, its cap and spend, and its rate limits."""
	require_ai(team)
	keys = GroveClient.from_settings().list_keys(team)
	return [{field: row.get(field) for field in KEY_FIELDS} for row in keys]


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def create_api_key(
	team: str | None = None, label: str | None = None, geography: str | None = None, cap: float | None = None
) -> dict:
	"""Mint a key for the team in `geography` (Grove's default when none) with `cap` USD to
	spend (a prepaid team's key needs one above zero), and return its secret. This is the only
	time it is shown. `models` is what it may call, for the quickstart."""
	require_ai(team)
	label = (label or "").strip()
	if not label:
		frappe.throw(_("A label is required."))

	client = GroveClient.from_settings()
	key = client.provision_key(team, label, geography or None, flt(cap) if cap is not None else None)
	return {
		"name": key["name"],
		"label": label,
		"geography": key["geography"],
		"gateway_url": key["gateway_url"],
		"api_key": key["api_key"],
		"models": ai.get_key_models(team, key["name"]),
	}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def update_api_key(team: str | None = None, key: str | None = None, cap: float | None = None) -> dict:
	"""Change what one of the team's keys may spend. Grove refuses a cap the balance cannot
	cover, and another team's key."""
	require_ai(team)
	row = GroveClient.from_settings().update_key(team, key, flt(cap))
	return {field: row.get(field) for field in KEY_FIELDS}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_api_key_models(team: str | None = None, key: str | None = None) -> list[dict]:
	"""The models one of the team's keys may call."""
	require_ai(team)
	return ai.get_key_models(team, key)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def revoke_api_key(team: str | None = None, key: str | None = None) -> dict:
	"""Revoke one of the team's keys. Grove refuses another team's key."""
	require_ai(team)
	GroveClient.from_settings().revoke_key(team, key)
	return {"name": key}


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
