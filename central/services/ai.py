from __future__ import annotations

import frappe

from central.integrations.grove import GroveClient
from central.services.doctype.team_service.team_service import AI_SERVICE


def get_ai_service(team: str) -> str | None:
	"""The team's AI Team Service, None while AI is off for it."""
	return frappe.db.get_value("Team Service", {"team": team, "add_on_service": AI_SERVICE})


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


def register_team(team: str, free: bool = True) -> dict:
	"""Register the team at Grove under the team id, with its alert email. A repeat sends the
	email again and changes nothing else; `free=False` keeps the Free setting Grove already has."""
	return GroveClient.from_settings().provision_team(team, get_alert_email(team), free=free) or {}


def on_alert_address_update(doc, method: str | None = None) -> None:
	"""Team and Billing Profile hook: send a changed alert address to Grove. A Billing Profile
	is named by its team. A no-op when the address stayed or AI is off."""
	field = "owner_user" if doc.doctype == "Team" else "email"
	if not doc.has_value_changed(field) or not get_ai_service(doc.name):
		return

	# No retry: if Grove is down now, it keeps the old address until the next change.
	frappe.enqueue("central.services.ai.register_team", team=doc.name, free=False, enqueue_after_commit=True)


def get_overview(team: str) -> dict:
	"""The team's AI at a glance: `balance`, this month's `usage`, and the `geographies` a key
	may be minted in. What a key may call and how fast is the key's own: see `list_api_keys`."""
	client = GroveClient.from_settings()
	return {
		"balance": client.get_balance(team),
		"usage": get_month_usage(team),
		"geographies": client.list_geographies(),
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


def get_models(geography: str | None = None) -> list[dict]:
	"""What a new key in `geography` (Grove's default when None) starts with: the published
	models of its default group, what each takes and gives, and the API surfaces it answers on."""
	return shape_models(GroveClient.from_settings().list_models(geography=geography))


def get_key_models(team: str, key: str) -> list[dict]:
	"""The models Grove lets one key call, as its geography serves them. Grove decides; Central
	only shows them."""
	return shape_models(GroveClient.from_settings().list_models(team, key))


def shape_models(rows: list[dict]) -> list[dict]:
	return [
		{
			"name": row["name"],
			"input_modalities": row.get("input_modalities", []),
			"output_modalities": row.get("output_modalities", []),
			"dialects": row["dialects"],
		}
		for row in rows
	]


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
