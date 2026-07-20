from __future__ import annotations

import frappe

from central.services.drivers.base import get_driver

_LLM_SERVICE = "llm"
_TOKEN_RESOURCE = "Tokens"


def sync_models(service: str = _LLM_SERVICE) -> int:
	"""Refresh the local LLM Model catalog from the backend's published models.
	The backend owns which models exist; Central only assigns the tier."""
	driver, backend = _driver_and_backend(service)
	published = {row["name"]: row.get("display_name") for row in driver.list_models(backend)}

	known = set(frappe.get_all("LLM Model", pluck="name"))
	for model_key, display_name in published.items():
		_upsert_model(model_key, display_name, exists=model_key in known)

	# Never delete (it would drop the assigned tier); just unpublish what Grove dropped,
	# in one statement rather than a write per model.
	stale = list(known - set(published))
	if stale:
		model = frappe.qb.DocType("LLM Model")
		frappe.qb.update(model).set(model.is_published, 0).where(model.name.isin(stale)).run()

	return len(published)


def resolve_provision_options(plan: str | None) -> dict:
	"""Turn a plan into Grove provisioning options: the concrete allowed-model list
	(derived from the plan's tiers) and a token cap (prepaid plans only)."""
	tiers = _allowed_tiers(plan)
	allowed_models = None

	if tiers:
		models = frappe.get_all("LLM Model", filters={"tier": ["in", tiers], "is_published": 1}, pluck="name")
		# An empty allow-list can't be sent to Grove (blank means "all"), so a policy
		# that resolves to zero models is a misconfiguration — refuse, never grant all.
		if not models:
			frappe.throw(
				frappe._("Plan {0} grants tiers ({1}) with no published models. Fix the model catalogue.").format(
					plan, ", ".join(tiers)
				)
			)
		allowed_models = ",".join(sorted(models))

	return {"allowed_models": allowed_models, "token_limit": _token_limit(plan)}


def included_models(plan: str | None) -> list[dict]:
	"""Models a plan grants, for display. Non-throwing, unlike resolve_provision_options —
	an empty result just means nothing is published yet."""
	filters = {"is_published": 1}
	tiers = _allowed_tiers(plan)
	if tiers:
		filters["tier"] = ["in", tiers]

	return frappe.get_all("LLM Model", filters=filters, fields=["name", "tier"], order_by="tier, name")


def pull_usage(service: str = _LLM_SERVICE) -> dict:
	"""Reconcile Grove's cumulative monthly token usage into billing, per team. AI
	Tokens is authoritative-metered, so the running total is reported (replaced). One
	team's failure is isolated and skipped — the next run corrects it."""
	driver, backend = _driver_and_backend(service)

	reported, failures, first_traceback = 0, [], None
	for team, emails in _team_credentials(service).items():
		try:
			usage = driver.fetch_usage(backend, emails)
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


def _upsert_model(model_key: str, display_name: str | None, exists: bool) -> None:
	if exists:
		frappe.db.set_value("LLM Model", model_key, {"display_name": display_name, "is_published": 1})
		return

	frappe.get_doc(
		{"doctype": "LLM Model", "model_key": model_key, "display_name": display_name, "tier": "Balanced", "is_published": 1}
	).insert(ignore_permissions=True)


def _allowed_tiers(plan: str | None) -> list[str]:
	if not plan or not frappe.db.exists("LLM Plan Policy", plan):
		return []

	return frappe.get_all("LLM Plan Tier", filters={"parent": plan}, pluck="tier")


def _token_limit(plan: str | None) -> int | None:
	# Prepaid plans hard-cap at the bundled allowance; postpaid bills overage, no cap.
	category = frappe.db.get_value("Plan", plan, "category", cache=True) if plan else None
	if not category or frappe.db.get_value("Plan Category", category, "settlement_mode", cache=True) != "Prepaid Pack":
		return None

	allowance = frappe.db.get_value("Plan Includes", {"parent": plan, "resource_type": _TOKEN_RESOURCE}, "quantity")
	return int(allowance) if allowance else None


def _team_credentials(service: str) -> dict[str, list[str]]:
	# Active site credentials for the service, grouped team -> [grove emails].
	credential = frappe.qb.DocType("Site Service Credential")
	managed = frappe.qb.DocType("Managed Service")

	rows = (
		frappe.qb.from_(credential)
		.join(managed)
		.on(credential.managed_service == managed.name)
		.select(managed.team.as_("team"), credential.provider_ref.as_("email"))
		.where(
			(managed.add_on_service == service)
			& (credential.status == "Active")
			& (credential.provider_ref.isnotnull())
		)
	).run(as_dict=True)

	grouped: dict[str, list[str]] = {}
	for row in rows:
		grouped.setdefault(row.team, []).append(row.email)

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
