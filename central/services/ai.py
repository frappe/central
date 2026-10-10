from __future__ import annotations

import frappe

from central.integrations.grove import GroveClient
from central.services.doctype.team_service.team_service import AI_SERVICE


def get_ai_service(team: str) -> str | None:
	"""The team's AI Team Service, None while AI is off for it."""
	return frappe.db.get_value("Team Service", {"team": team, "add_on_service": AI_SERVICE})


def get_gateway_url(team: str) -> str | None:
	"""Where the team's keys call, as Grove answered when the team was registered."""
	return frappe.db.get_value("Team Service", {"team": team, "add_on_service": AI_SERVICE}, "endpoint_url")


def enable(team: str) -> str:
	"""Turn AI on for a team. Safe to repeat. The record registers the team at Grove before it
	saves, so a refusal there leaves no row here."""
	# Two enables at once would both pass the check below; the team row serialises them.
	frappe.db.get_value("Team", team, "name", for_update=True)
	if name := get_ai_service(team):
		return name

	service = frappe.get_doc(
		{"doctype": "Team Service", "team": team, "add_on_service": AI_SERVICE, "status": "Active"}
	)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.insert(ignore_permissions=True)

	return service.name


def get_alert_email(team: str) -> str:
	"""Where Grove sends the team's alerts: the billing contact when set, else the owner."""
	if email := frappe.db.get_value("Billing Profile", team, "email"):
		return email

	owner = frappe.db.get_value("Team", team, "owner_user")

	# The User's name is not always an address: Administrator is not one.
	return frappe.db.get_value("User", owner, "email")


def register_grove_user(team: str, free: bool = True) -> dict:
	"""Register the team as a Grove user named by the team id, with its alert email. Grove picks
	its geography and answers with it and its `gateway_url`. A repeat sends the email again and
	changes nothing else; `free=False` keeps the Free setting Grove already has."""
	return GroveClient.from_settings().provision_user(team, get_alert_email(team), free=free) or {}


def on_alert_address_update(doc, method: str | None = None) -> None:
	"""Team and Billing Profile hook: send a changed alert address to Grove. A Billing Profile
	is named by its team. A no-op when the address stayed or AI is off."""
	field = "owner_user" if doc.doctype == "Team" else "email"
	if not doc.has_value_changed(field) or not get_ai_service(doc.name):
		return

	# No retry: if Grove is down now, it keeps the old address until the next change.
	frappe.enqueue(
		"central.services.ai.register_grove_user", team=doc.name, free=False, enqueue_after_commit=True
	)


def get_overview(team: str) -> dict:
	"""The team's AI at a glance: `models`, `rate_limits`, `balance` and this month's `usage`."""
	return {
		"models": get_reachable_models(team),
		"rate_limits": get_rate_limits(team),
		"balance": GroveClient.from_settings().get_balance(team),
		"usage": get_month_usage(team),
	}


def get_month_usage(team: str) -> dict:
	"""This month's requests, tokens and cost, with the window and Grove's as-of time."""
	usage = GroveClient.from_settings().get_usage([team], period="This Month")
	return {
		**(usage.get(team) or {"requests": 0, "tokens": 0, "cost": 0}),
		"from_date": usage["from_date"],
		"to_date": usage["to_date"],
		"as_of": usage["as_of"],
	}


def get_reachable_models(team: str) -> list[dict]:
	"""The models Grove lets the team call: what each takes and gives, and the API surfaces
	(openai, anthropic) it answers on. Grove decides; Central only shows them."""
	return [
		{
			"name": row["name"],
			"input_modalities": row.get("input_modalities", []),
			"output_modalities": row.get("output_modalities", []),
			"dialects": row["dialects"],
		}
		for row in GroveClient.from_settings().list_models(team)
	]


def get_rate_limits(team: str) -> list[dict]:
	"""The limits Grove counts across every key of the team: rows of `metric` (requests,
	total_tokens), `window` (1m, 1h, 1d, 1M) and `value`. No rows is no limit."""
	rows = GroveClient.from_settings().get_limits(team)
	return [{"metric": row["metric"], "window": row["window"], "value": row["value"]} for row in rows]


def get_usage_report(team: str, period: str, key_hash: str | None = None) -> dict:
	"""What the team used over a period, or one key of theirs by `key_hash`: requests and cost,
	in total, per model, and per day for a chart. Grove does the sums and charged the cost."""
	usage = GroveClient.from_settings().get_usage([team], period=period, key_hash=key_hash)
	return {
		"period": period,
		"from_date": usage["from_date"],
		"to_date": usage["to_date"],
		"as_of": usage["as_of"],
		"totals": usage.get(team) or {"requests": 0, "tokens": 0, "cost": 0},
		"models": usage["model_summary"],
		"daily": get_every_day(usage),
	}


def get_every_day(usage: dict) -> list[dict]:
	"""Grove's per-day rows with the quiet days filled in: one row per day of the period and
	model, zeros where the model was not used, so a chart shows the whole period."""
	used = {(row["day"], row["model"]): row for row in usage["daily_summary"]}
	models = [row["model"] for row in usage["model_summary"]]
	days = frappe.utils.date_diff(usage["to_date"], usage["from_date"]) + 1

	return [
		used.get((day, model)) or {"day": day, "model": model, "requests": 0, "tokens": 0, "cost": 0}
		for day in (str(frappe.utils.add_days(usage["from_date"], offset)) for offset in range(days))
		for model in models
	]
