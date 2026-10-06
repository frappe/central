from __future__ import annotations

import frappe

from central.integrations.grove import GroveClient
from central.services.doctype.team_service.team_service import AI_SERVICE

TOKEN_RESOURCE = "Tokens"


def get_ai_service(team: str) -> str | None:
	"""The team's AI Team Service, None while AI is off for it."""
	return frappe.db.get_value("Team Service", {"team": team, "add_on_service": AI_SERVICE})


def enable(team: str) -> str:
	"""Turn AI on for a team. Safe to repeat. The record registers the team at Grove before it
	saves, so a refusal there leaves no row here."""
	if name := get_ai_service(team):
		return name

	service = frappe.get_doc(
		{"doctype": "Team Service", "team": team, "add_on_service": AI_SERVICE, "status": "Active"}
	)
	# The route checked service:manage; Team Service is operator-only because it holds secrets.
	service.insert(ignore_permissions=True)
	return service.name


def register_grove_user(team: str, free: bool = True) -> None:
	"""Register the team as a Grove user named by the team id, with the team owner's email for
	alerts. Grove picks its geography. A repeat sends the email again and changes nothing else;
	`free=False` keeps the Free setting Grove already has."""
	owner = frappe.db.get_value("Team", team, "owner_user")
	# The User's name is not always an address: Administrator is not one.
	email = frappe.db.get_value("User", owner, "email")
	GroveClient.from_settings().provision_user(team, email, free=free)


def on_team_update(doc, method: str | None = None) -> None:
	"""Send a new team owner's email to Grove. A no-op when the owner stayed or AI is off."""
	if not doc.has_value_changed("owner_user") or not get_ai_service(doc.name):
		return

	# No retry: if Grove is down now, it keeps the old email until the next owner change.
	frappe.enqueue(
		"central.services.ai.register_grove_user", team=doc.name, free=False, enqueue_after_commit=True
	)


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


def get_rate_limits(team: str) -> dict:
	"""The per-minute limits Grove counts across every key of the team. None is no limit."""
	rows = GroveClient.from_settings().get_limits(team)
	per_minute = {row["metric"]: row["value"] for row in rows if row["window"] == "1m"}
	return {
		"requests_per_minute": per_minute.get("requests"),
		"tokens_per_minute": per_minute.get("total_tokens"),
	}


def get_usage_report(team: str, period: str, key_hash: str | None = None) -> dict:
	"""What the team used over a period, or one key of theirs by `key_hash`: requests and cost,
	in total, per model, and per day for a chart. Grove does the sums and charged the cost."""
	usage = GroveClient.from_settings().get_usage([team], period=period, key_hash=key_hash)
	return {
		"period": period,
		"from_date": usage["from_date"],
		"to_date": usage["to_date"],
		"as_of": usage["as_of"],
		"totals": usage.get(team) or {"requests": 0, "cost": 0},
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
		used.get((day, model)) or {"day": day, "model": model, "requests": 0, "cost": 0}
		for day in (str(frappe.utils.add_days(usage["from_date"], offset)) for offset in range(days))
		for model in models
	]


def pull_usage() -> dict:
	"""Reconcile each AI team's monthly billable tokens at Grove into billing. AI Tokens is
	authoritative-metered, so the running total replaces the last one. One team's failure is
	skipped; the next run corrects it."""
	teams = frappe.get_all(
		"Team Service", filters={"add_on_service": AI_SERVICE, "status": "Active"}, pluck="team"
	)
	if not teams:
		return {"teams_reported": 0, "teams_failed": 0}

	client = GroveClient.from_settings()
	reported, failures, first_traceback = 0, [], None
	for team in teams:
		try:
			usage = client.get_usage([team])
			billable = (usage.get(team) or {}).get("billable_tokens") or 0
			if report_tokens(team, billable):
				reported += 1
		except Exception:
			failures.append(team)
			first_traceback = first_traceback or frappe.get_traceback()

	if failures:
		# Logged once, not per team, so a Grove outage cannot flood the Error Log.
		frappe.log_error(
			title="AI usage reconciliation failures",
			message=f"{len(failures)} team(s) failed: {', '.join(failures[:20])}\n\n{first_traceback}",
		)

	return {"teams_reported": reported, "teams_failed": len(failures)}


def report_tokens(team: str, quantity: float) -> bool:
	from central.billing.catalog.services import resolve_service_subject
	from central.billing.catalog.subscriptions import active_segment_for_resource
	from central.billing.revenue.metering import ingest_rollup

	subject = resolve_service_subject(team, TOKEN_RESOURCE)
	if not subject:
		return False

	segment = active_segment_for_resource(subject)
	today = frappe.utils.getdate()
	start = today.replace(day=1)
	ingest_rollup(
		{
			"resource_id": subject,
			"team": segment.team if segment else team,
			"cluster": segment.cluster if segment else None,
			"currency": segment.currency if segment else None,
			"resource_type": TOKEN_RESOURCE,
			"meter_type": "Counter",
			"quantity": frappe.utils.flt(quantity),
			"period_start": str(start),
			"period_end": str(frappe.utils.get_last_day(start)),
			"idempotency_key": f"{subject}|{TOKEN_RESOURCE}|{start.strftime('%Y-%m')}",
			"sequence": 0,
		}
	)
	return True
