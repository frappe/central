# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The operator-facing entry point onto projections.

Lives in the API layer because that is where whitelisted endpoints belong — the
projection package stays domain-only and exposes no HTTP surface.

Cross-team by nature — an operator asks about somebody else's money — so this is
gated on the operator capability rather than on team scoping, and every call is
logged with who asked and about whom.
"""

import frappe

from central.billing import authz
from central.billing.projection import engine


@frappe.whitelist()
def project_team(
	team: str,
	period_start: str | None = None,
	period_end: str | None = None,
	today: str | None = None,
	mode: str = "Derived",
	assume: str | None = None,
) -> dict:
	"""Project one team over one period.

	Defaults to the month in flight, which is the question an operator usually has:
	what is this team about to be billed, and what happens after that.
	"""
	authz.require_operator()

	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.getdate(period_start or frappe.utils.get_first_day(today))
	period_end = frappe.utils.getdate(period_end or frappe.utils.get_last_day(period_start))

	frappe.logger("billing").info(
		f"projection: {frappe.session.user} projected {team} "
		f"for {period_start}..{period_end} as of {today}"
	)
	return engine.project(team, period_start, period_end, today=today, mode=mode, assume=assume)


@frappe.whitelist()
def project_team_months(
	team: str,
	start: str | None = None,
	months: int = 6,
	today: str | None = None,
	mode: str = "Derived",
	assume: str | None = None,
) -> dict:
	"""Roll a team forward over several months, carrying what each one changes.

	The question a single period cannot answer: not what September costs, but when the
	credits run out and what happens after.
	"""
	authz.require_operator()

	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	start = frappe.utils.getdate(start or frappe.utils.get_first_day(today))
	months = max(1, min(frappe.utils.cint(months), 24))

	frappe.logger("billing").info(
		f"projection: {frappe.session.user} rolled {team} forward {months} months "
		f"from {start} as of {today}"
	)
	return engine.project_months(team, start, months=months, today=today, mode=mode, assume=assume)


@frappe.whitelist(methods=["POST"])
def start_cohort_projection(
	filters: str | None = None,
	months: int = 1,
	period_start: str | None = None,
) -> dict:
	"""Size a cohort and, if we are willing to project it, enqueue the batch.

	Refuses rather than queues when the cohort is over budget — and the refusal carries
	the count, the cost and what would narrow it, because a bound with no way forward is
	one people route around.
	"""
	authz.require_operator()

	from central.billing.projection import batch, cohort

	parsed = frappe.parse_json(filters) if filters else {}
	parsed = {k: v for k, v in (parsed or {}).items() if v}
	months = max(1, min(frappe.utils.cint(months), 24))

	try:
		sizing = cohort.require_within_budget(parsed, months)
	except cohort.CohortTooLargeError as e:
		frappe.throw(
			str(e)
			+ " "
			+ frappe._("Narrow it by {0}, shorten the range, or take a sample.").format(
				", ".join(cohort.narrowing_hints(parsed)) or frappe._("adding a filter")
			),
			title=frappe._("Too large to project"),
		)

	name = batch.start(parsed, period_start=period_start, months=months)
	frappe.logger("billing").info(
		f"projection: {frappe.session.user} started cohort batch {name} "
		f"({sizing.teams} teams, {months} months)"
	)
	return {"batch": name, "teams": sizing.teams, "months": months}


@frappe.whitelist(methods=["POST"])
def sample_cohort(
	filters: str | None = None,
	months: int = 1,
	size: int = 500,
	period_start: str | None = None,
) -> dict:
	"""Project a stratified sample of a cohort too large to project whole."""
	authz.require_operator()

	from central.billing.projection import batch, cohort

	parsed = {k: v for k, v in (frappe.parse_json(filters) if filters else {}).items() if v}
	months = max(1, min(frappe.utils.cint(months), 24))
	size = max(1, min(frappe.utils.cint(size) or 500, 5000))

	drawn = cohort.sample(parsed, size)
	name = batch.start_sampled(parsed, period_start=period_start, months=months, size=size)
	frappe.logger("billing").info(
		f"projection: {frappe.session.user} sampled {drawn.size} of {drawn.population} teams "
		f"into batch {name}"
	)
	return {
		"batch": name,
		"sample_size": drawn.size,
		"population": drawn.population,
		"strata": drawn.strata,
	}


@frappe.whitelist()
def size_cohort(filters: str | None = None, months: int = 1) -> dict:
	"""What projecting this cohort would cost, without projecting anything."""
	authz.require_operator()

	from central.billing.projection import cohort

	parsed = frappe.parse_json(filters) if filters else {}
	sizing = cohort.estimate({k: v for k, v in (parsed or {}).items() if v}, months)
	return dict(sizing)


@frappe.whitelist()
def project_scenario(scenario: str, today: str | None = None) -> dict:
	"""Project a saved scenario — its team, its period, its overrides."""
	authz.require_operator()

	from central.billing.projection import scenario as scenarios

	frappe.logger("billing").info(
		f"projection: {frappe.session.user} projected scenario {scenario}"
	)
	return scenarios.project(scenario, today=today)


@frappe.whitelist(methods=["POST"])
def save_scenario_result(scenario: str, today: str | None = None) -> dict:
	"""Project a scenario and record the answer on it."""
	authz.require_operator()

	from central.billing.projection import scenario as scenarios

	return scenarios.project_and_save(scenario, today=today)


@frappe.whitelist()
def compare_scenario(scenario: str, today: str | None = None) -> dict:
	"""The same team as configured and as the scenario pretends, side by side."""
	authz.require_operator()

	from central.billing.projection import scenario as scenarios

	return scenarios.compare(scenario, today=today)


@frappe.whitelist()
def scenario_library() -> list[dict]:
	"""The shelf of canned questions."""
	authz.require_operator()

	from central.billing.projection import library

	return library.catalogue()


@frappe.whitelist()
def project_from_library(key: str, team: str, period_start: str | None = None, today: str | None = None) -> dict:
	"""Apply a catalogue scenario to a real team and project it, without saving."""
	authz.require_operator()

	from central.billing.projection import library, scenario as scenarios

	doc = library.build(key, team, period_start=period_start, today=today)
	frappe.logger("billing").info(
		f"projection: {frappe.session.user} ran library scenario {key} on {team}"
	)
	out = scenarios.project(doc, today=today)
	out["library"] = {"key": key, **{k: v for k, v in library.SCENARIOS[key].items() if k in ("title", "question", "look_for")}}
	return out


@frappe.whitelist()
def check_scenario_drift(scenario: str, today: str | None = None) -> dict:
	"""Whether a saved scenario now answers differently than when it was saved."""
	authz.require_operator()

	from central.billing.projection import scenario as scenarios

	return scenarios.check_drift(scenario, today=today)


@frappe.whitelist()
def compare_cohort_batches(live: str, altered: str) -> dict:
	"""How far a change reaches, across two batches of the same teams."""
	authz.require_operator()

	from central.billing.projection import batch

	return batch.compare_batches(live, altered)
