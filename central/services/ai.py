from __future__ import annotations

from datetime import UTC, datetime

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


def stop_team_keys(team: str) -> None:
	"""Stop every live key of a team that is closing. Each cap goes to 0 first, which Grove allows at
	any time, so no key spends again. Then the keys old enough to revoke are revoked."""
	if not get_ai_service(team):
		return

	client = GroveClient.from_settings()
	live = [key for key in client.get_figures(team)["keys"] if key["status"] == "active"]
	if not live:
		return

	client.update_caps(team, {key["name"]: 0 for key in live})
	# Grove sends UTC timestamps such as "2026-10-06T10:30:00Z".
	now = datetime.now(UTC)
	for key in live:
		if datetime.fromisoformat(key["revocable_at"].replace("Z", "+00:00")) <= now:
			client.revoke_key(team, key["name"])


def set_team_suspended(team: str, suspended: bool) -> None:
	"""Pause or resume every key of a team at Grove. Unlike revoking, this can be undone."""
	if get_ai_service(team):
		GroveClient.from_settings().update_team(team, suspended=suspended)


def register_team(team: str) -> dict:
	"""Register the team at Grove under the team id, then send the name of its tier. Grove keeps
	nothing else about the team."""
	client = GroveClient.from_settings()
	registered = client.provision_team(team) or {}
	client.update_team(**get_team_limits(team))
	return registered


def get_team_limits(team: str) -> dict:
	"""What Central tells Grove about the team, and the body of the Webhook that carries it (a
	`jinja` hook method, rendered when the delivery runs): the name of its tier, whose key count,
	monthly spend limit and rate limits Grove holds (untiered: "", Grove's default tier), and
	`observed_at`, the Billing Profile's `modified`, which Grove keeps so a retried or reordered
	delivery never overwrites a newer one (no profile yet: None, and the body applies)."""
	from central.billing.catalog.entitlements import get_team_caps

	observed_at = frappe.db.get_value("Billing Profile", team, "modified")
	return {
		"team": team,
		"tier": get_team_caps(team).tier or "",
		"observed_at": str(observed_at) if observed_at else None,
	}


def on_level_update(doc, method: str | None = None) -> None:
	"""Trust Tier Level hook: a renamed label renames the Tier at Grove, with every team on it.
	Direct and inside the save, since a Webhook body carries no old value: with Grove down the
	save fails and is tried again later. A Central not enrolled at Grove still edits its levels."""
	before = doc.get_doc_before_save()
	if not (before and before.tier and doc.has_value_changed("tier")):
		return
	if frappe.get_cached_doc("AI Settings").is_enrolled:
		GroveClient.from_settings().rename_tier(before.tier, doc.tier)


def get_overview(team: str) -> dict:
	"""The team's AI at a glance: `spend` (this month's, and the keys' caps against the tier's
	spend limit), this month's `usage`, and the `geographies` a key may be minted in. What a key may call and how fast is the key's own: see `list_api_keys`."""
	client = GroveClient.from_settings()
	figures = client.get_figures(team)
	return {
		"spend": figures["spend"],
		"usage": get_month_usage(team, figures["usage"]),
		"geographies": client.list_geographies(),
	}


def get_month_usage(team: str, usage: dict) -> dict:
	"""This month's requests, tokens and cost off the team's figures, with the window, Grove's
	as-of time and one total per day so far (`daily`) for the overview's sparklines."""
	return {
		**(usage.get(team) or {"requests": 0, "tokens": 0, "cost": 0}),
		"from_date": usage["from_date"],
		"to_date": usage["to_date"],
		"as_of": usage["as_of"],
		"daily": get_day_totals(usage),
	}


def get_day_totals(usage: dict) -> list[dict]:
	"""Every day of the period in order, each with the team's requests, tokens and cost summed
	over its models, zeros on a quiet day: one point per day for a sparkline."""
	days = frappe.utils.date_diff(usage["to_date"], usage["from_date"]) + 1
	totals = {
		str(frappe.utils.add_days(usage["from_date"], offset)): {"requests": 0, "tokens": 0, "cost": 0}
		for offset in range(days)
	}
	for row in usage["daily_summary"]:
		for field in ("requests", "tokens", "cost"):
			totals[row["day"]][field] += row[field]
	return [{"day": day, **fields} for day, fields in totals.items()]


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
			"provider": row.get("provider"),
			"model_id": row.get("model_id"),
			"zero_data_retention": bool(row.get("zero_data_retention")),
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
