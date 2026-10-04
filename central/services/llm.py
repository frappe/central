from __future__ import annotations

import frappe

from central.services.drivers.base import get_driver

_LLM_SERVICE = "llm"
_TOKEN_RESOURCE = "Tokens"


def pull_usage(service: str = _LLM_SERVICE) -> dict:
	"""Reconcile Grove's cumulative monthly token usage into billing, per team. AI
	Tokens is authoritative-metered, so the running total is reported (replaced). One
	team's failure is isolated and skipped — the next run corrects it."""
	driver, backend = _driver_and_backend(service)

	reported, failures, first_traceback = 0, [], None
	for team, users in _team_credentials(service).items():
		try:
			usage = driver.fetch_usage(backend, users)
			billable = sum(
				v["billable_tokens"] for v in usage.values() if isinstance(v, dict) and "billable_tokens" in v
			)
			if _report_tokens(team, billable):
				reported += 1
		except Exception:
			failures.append(team)
			first_traceback = first_traceback or frappe.get_traceback()

	if failures:
		# Log once (not per team) so a backend outage can't flood the Error Log.
		frappe.log_error(
			title="LLM usage reconciliation failures",
			message=f"{len(failures)} team(s) failed: {', '.join(failures[:20])}\n\n{first_traceback}",
		)

	return {"teams_reported": reported, "teams_failed": len(failures)}


def _team_credentials(service: str) -> dict[str, list[str]]:
	# Every active grove identity the service issued — per-site credentials and team-level
	# API keys alike — grouped team -> [grove users]. Both subject types drain the same
	# team token meter, so both must be reconciled or a whole channel bills nothing.
	credential = frappe.qb.DocType("Service Credential")
	managed = frappe.qb.DocType("Managed Service")

	rows = (
		frappe.qb.from_(credential)
		.join(managed)
		.on(credential.managed_service == managed.name)
		.select(managed.team.as_("team"), credential.provider_ref.as_("grove_user"))
		.where(
			(managed.add_on_service == service)
			& (credential.status == "Active")
			& (credential.provider_ref.isnotnull())
		)
	).run(as_dict=True)

	grouped: dict[str, list[str]] = {}
	for row in rows:
		grouped.setdefault(row.team, []).append(row.grove_user)

	return grouped


def _report_tokens(team: str, quantity: float) -> bool:
	from central.billing.catalog.services import resolve_service_subject
	from central.billing.catalog.subscriptions import active_segment_for_resource
	from central.billing.revenue.metering import ingest_rollup

	subject = resolve_service_subject(team, _TOKEN_RESOURCE)
	if not subject:
		return False

	segment = active_segment_for_resource(subject)
	period_start, period_end, tag = _current_month()
	ingest_rollup(
		{
			"resource_id": subject,
			"team": segment.team if segment else team,
			"cluster": segment.cluster if segment else None,
			"currency": segment.currency if segment else None,
			"resource_type": _TOKEN_RESOURCE,
			"meter_type": "Counter",
			"quantity": frappe.utils.flt(quantity),
			"period_start": period_start,
			"period_end": period_end,
			"idempotency_key": f"{subject}|{_TOKEN_RESOURCE}|{tag}",
			"sequence": 0,
		}
	)
	return True


def _current_month() -> tuple[str, str, str]:
	today = frappe.utils.getdate()
	start = today.replace(day=1)
	return str(start), str(frappe.utils.get_last_day(start)), start.strftime("%Y-%m")


def _driver_and_backend(service: str):
	handler = frappe.db.get_value("Add-on Service", service, "handler_key")
	backend_name = frappe.db.get_value("Service Backend", {"service": service, "is_active": 1}, "name")
	if not handler or not backend_name:
		frappe.throw(frappe._("No active backend configured for {0}.").format(service))

	return get_driver(handler), frappe.get_doc("Service Backend", backend_name)


def register_grove_user(team: str, service: str = _LLM_SERVICE, free: bool = True) -> str:
	"""Register the team as a Grove user and return its id at Grove: the team id. Every
	key and the usage of the team hang on it. Grove gets the email of the team owner for
	alerts. A repeat sends the email again and changes nothing else at Grove. `free`
	marks the Grove user as Free; send False to keep the setting that Grove has."""
	owner = frappe.db.get_value("Team", team, "owner_user")

	driver, backend = _driver_and_backend(service)
	driver.provision_user(backend, team, owner, free=free)

	return team


def on_team_update(doc, method: str | None = None) -> None:
	"""Send the email of a new team owner to Grove. Fires on every Team save; a no-op
	when the owner did not change or the team has no LLM Hosting."""
	if not doc.has_value_changed("owner_user"):
		return

	if not frappe.db.exists("Managed Service", {"team": doc.name, "add_on_service": _LLM_SERVICE}):
		return

	# No retry: if Grove is down now, it keeps the old email until the next owner change.
	frappe.enqueue(
		"central.services.llm.register_grove_user", team=doc.name, free=False, enqueue_after_commit=True
	)


def get_reachable_models(user: str, service: str = _LLM_SERVICE) -> list[dict]:
	"""The models Grove lets a Grove user call, and the API surfaces (openai, anthropic) each
	answers on. Grove decides; Central only shows them."""
	driver, backend = _driver_and_backend(service)

	return [
		{"name": row["name"], "modality": row.get("modality"), "dialects": row["dialects"]}
		for row in driver.list_models(backend, user)
	]


def get_rate_limits(user: str, service: str = _LLM_SERVICE) -> dict:
	"""The per-minute limits Grove counts across every key of a Grove user. Grove decides;
	Central only shows them. None means no limit on that metric."""
	driver, backend = _driver_and_backend(service)
	per_minute = {
		row["metric"]: row["value"] for row in driver.get_limits(backend, user) if row["window"] == "1m"
	}

	return {
		"requests_per_minute": per_minute.get("requests"),
		"tokens_per_minute": per_minute.get("total_tokens"),
	}


def get_usage_report(
	user: str, period: str, service: str = _LLM_SERVICE, key_hash: str | None = None
) -> dict:
	"""What a Grove user used over a period, or one key of theirs by `key_hash`: requests and
	cost, in total, per model, and per day for a chart. Grove does the sums; the cost is what
	Grove charged."""
	driver, backend = _driver_and_backend(service)
	usage = driver.fetch_usage(backend, [user], period=period, key_hash=key_hash)

	return {
		"period": period,
		"from_date": usage["from_date"],
		"to_date": usage["to_date"],
		"as_of": usage["as_of"],
		"totals": usage.get(user) or {"requests": 0, "cost": 0},
		"models": usage["model_summary"],
		"daily": _every_day(usage),
	}


def _every_day(usage: dict) -> list[dict]:
	"""Grove's per-day rows with the quiet days filled in: one row per day of the period
	and model, zeros where the model was not used, so a chart shows the whole period."""
	used = {(row["day"], row["model"]): row for row in usage["daily_summary"]}
	models = [row["model"] for row in usage["model_summary"]]
	days = frappe.utils.date_diff(usage["to_date"], usage["from_date"]) + 1

	return [
		used.get((day, model)) or {"day": day, "model": model, "requests": 0, "cost": 0}
		for day in (str(frappe.utils.add_days(usage["from_date"], offset)) for offset in range(days))
		for model in models
	]
