# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Who a cohort projection covers, and whether we are willing to project it.

Two cohort questions look alike and are not. *Who gets suspended, and when* needs no
rating — it is the dunning ladder over invoices that already exist, so it scales with
delinquency rather than with the book and can run over everything. *What will these
teams be billed* has to rate each team, and at a few lakh teams a six-month projection
is on the order of **days** of compute, on a system that is concurrently provisioning
new signups. Queueing that does not solve it; it converts a long wait into a long load.

So the expensive path is bounded before it starts. The cohort is counted with one
indexed query, costed against a measured per-team-month rate, and **refused** if it
exceeds the budget. A warning that can be clicked through is not a bound: the person
clicking it is not the person paged when the database is on fire.

A refusal is not a dead end. A book-wide question is answered by projecting a
stratified sample and extrapolating, which is both faster and more honest than grinding
to a figure whose uncertainty is merely hidden.
"""

import frappe
from frappe.query_builder.functions import Count

# Measured on a dev bench: rating one team for one month, including the metered
# estimate, is a few hundred milliseconds. Deliberately a constant rather than a
# setting — it describes the machine, not a policy, and tuning it to make a cohort
# "fit" would defeat the bound.
SECONDS_PER_TEAM_MONTH = 0.2

# Used until an operator sets one; the DocType carries the same number.
DEFAULT_BUDGET_SECONDS = 300

# What an operator may wait for synchronously before it stops feeling like a page load.
SYNC_BUDGET_SECONDS = 40

# Cohorts are drawn from the teams that actually hold a subscription — the same
# population the billing run bills.
_SUBSCRIPTION = "Subscription"


def budget_seconds() -> int:
	"""The wall-clock a cohort projection may cost before it is refused.

	Configurable, because the right ceiling depends on the box. Worth reviewing like a
	production safety limit rather than a preference: raising it is how the bound stops
	being a bound.
	"""
	# Zero is treated as unset, deliberately. The field is an Int on a Single: it reads
	# as None until somebody saves Billing Settings, and as 0 forever after — so any
	# unrelated edit to that form would otherwise disable cohort projections site-wide,
	# silently. A budget of zero seconds is not a policy anyone wants either; it refuses
	# a one-team cohort.
	return frappe.utils.cint(
		frappe.db.get_single_value("Billing Settings", "projection_budget_seconds")
	) or DEFAULT_BUDGET_SECONDS


def _filtered_teams_query(filters: dict):
	"""The cohort as a query over teams holding a subscription, narrowed by profile.

	Currency, country and trust tier live on Billing Profile; cluster lives on the
	asset a subscription provisions. Everything here is a filter on data we already
	index — none of it costs a projection.
	"""
	filters = filters or {}
	sub = frappe.qb.DocType(_SUBSCRIPTION)
	query = frappe.qb.from_(sub)

	profile_keys = ("currency", "country", "trust_tier_level", "collection_mode")
	if any(filters.get(k) for k in profile_keys):
		profile = frappe.qb.DocType("Billing Profile")
		query = query.join(profile).on(profile.team == sub.team)
		for key in profile_keys:
			if filters.get(key):
				query = query.where(profile[key] == filters[key])

	if filters.get("cluster"):
		asset = frappe.qb.DocType("Asset")
		query = query.join(asset).on(asset.name == sub.asset_id)
		query = query.where(asset.cluster == filters["cluster"])

	if filters.get("account_standing"):
		query = query.where(sub.account_standing == filters["account_standing"])

	return query, sub


def teams_in_slice(filters: dict | None = None, after: str = "", until: str | None = None) -> list:
	"""The cohort's teams in one keyset slice — a page job's whole workload.

	Same shape as the billing run's own paging: the slice is re-derived from its bounds
	rather than carried as a list of names, so the job argument stays two strings
	however big the page.
	"""
	query, sub = _filtered_teams_query(filters)
	query = query.select(sub.team).distinct().where(sub.team > after)
	if until:
		query = query.where(sub.team <= until)
	return query.orderby(sub.team).run(pluck=True)


def pages(filters: dict | None = None, page_size: int = 500):
	"""Yield the cohort as bounded keyset pages, never the whole book in memory."""
	after = ""
	while True:
		query, sub = _filtered_teams_query(filters)
		page = (
			query.select(sub.team).distinct().where(sub.team > after).orderby(sub.team).limit(page_size)
		).run(pluck=True)
		if not page:
			return
		yield after, page[-1], page
		after = page[-1]


def count(filters: dict | None = None) -> int:
	"""How many teams the cohort selects.

	Aggregated in the database rather than by pulling the names back and measuring the
	list: sizing has to stay cheap at the scale it exists to protect against, or the
	bound becomes the load it was meant to prevent.
	"""
	query, sub = _filtered_teams_query(filters)
	counted = query.select(Count(sub.team).distinct()).run()
	return frappe.utils.cint(counted[0][0]) if counted else 0


def estimate(filters: dict | None = None, months: int = 1) -> frappe._dict:
	"""Size and cost the cohort before doing anything with it."""
	teams = count(filters)
	months = max(1, frappe.utils.cint(months))
	seconds = teams * months * SECONDS_PER_TEAM_MONTH
	budget = budget_seconds()
	return frappe._dict(
		teams=teams,
		months=months,
		estimated_seconds=round(seconds, 1),
		budget_seconds=budget,
		within_budget=seconds <= budget,
		# Small enough that an operator can simply wait for it.
		synchronous=seconds <= SYNC_BUDGET_SECONDS,
	)


class CohortTooLargeError(frappe.ValidationError):
	"""The cohort was refused. It carries what was asked for and what it would cost."""

	def __init__(self, sizing):
		self.sizing = sizing
		super().__init__(
			f"This cohort is too large to project: {sizing.teams} teams over "
			f"{sizing.months} months is about {_human(sizing.estimated_seconds)}, "
			f"against a budget of {_human(sizing.budget_seconds)}."
		)


def require_within_budget(filters: dict | None = None, months: int = 1) -> frappe._dict:
	"""Size the cohort and refuse it if projecting would cost more than the budget.

	Called before any team is rated. Refusing is the whole point — there is no
	`force` and no confirmation to click through, because the alternative to a bound
	is not a slower answer, it is a database nobody else can use.
	"""
	sizing = estimate(filters, months)
	if not sizing.within_budget:
		raise CohortTooLargeError(sizing)
	return sizing


def narrowing_hints(filters: dict | None = None) -> list[str]:
	"""Which filters are still unset — what an operator could add to get in range."""
	filters = filters or {}
	labels = {
		"currency": "currency",
		"country": "country",
		"cluster": "cluster",
		"trust_tier_level": "trust tier",
		"collection_mode": "collection mode",
		"account_standing": "standing",
	}
	return [label for key, label in labels.items() if not filters.get(key)]


def _human(seconds) -> str:
	seconds = frappe.utils.flt(seconds)
	if seconds < 90:
		return f"{round(seconds)} seconds"
	if seconds < 5400:
		return f"{round(seconds / 60)} minutes"
	if seconds < 172800:
		return f"{round(seconds / 3600, 1)} hours"
	return f"{round(seconds / 86400, 1)} days"


def run_in_progress(today=None) -> bool:
	"""Whether the monthly billing run still owes work for the closed period.

	A projection competing with the run for the database on the first of the month is
	exactly backwards: one of them is answering a question and the other is billing
	customers.
	"""
	from central.billing.revenue.invoicing.run import billing_run_status

	status = billing_run_status(today)
	return bool(status["pending_draft"] or status["pending_collection"])


# Strata are the axes a bill actually varies along: what you are charged in, and how
# much the ladder trusts you to owe. Sampling without them would over-represent
# whichever group is largest and quietly misreport the rest.
STRATA = ("currency", "trust_tier_level")


def strata_counts(filters: dict | None = None) -> list[frappe._dict]:
	"""How the cohort divides along the sampling axes, counted in the database."""
	sub = frappe.qb.DocType(_SUBSCRIPTION)
	profile = frappe.qb.DocType("Billing Profile")
	query = (
		frappe.qb.from_(sub)
		.join(profile)
		.on(profile.team == sub.team)
		.select(profile.currency, profile.trust_tier_level, Count(sub.team).distinct().as_("teams"))
		.groupby(profile.currency, profile.trust_tier_level)
	)
	for key in ("currency", "country", "collection_mode", "trust_tier_level"):
		if (filters or {}).get(key):
			query = query.where(profile[key] == filters[key])
	return query.run(as_dict=True)


def sample(filters: dict | None = None, size: int = 500) -> frappe._dict:
	"""Pick a stratified sample, and say what it stands for.

	The honest answer to a book-wide question is not to grind for two days. It is to
	project a few hundred teams chosen across the axes the bill varies along, extrapolate,
	and put the sample size next to the number so nobody mistakes it for a measurement.

	Each stratum is sampled in proportion to its share, with at least one team taken from
	any stratum that exists at all — a rung with three teams on it still deserves to be
	represented, or the extrapolation silently speaks only for the crowd.
	"""
	strata = strata_counts(filters)
	population = sum(row.teams for row in strata)
	if not population:
		return frappe._dict(teams=[], population=0, strata=[], size=0)

	size = min(max(1, frappe.utils.cint(size)), population)
	picked, detail = [], []
	for row in strata:
		share = row.teams / population
		take = max(1, round(size * share)) if row.teams else 0
		# Never claim more of a stratum than it holds.
		take = min(take, row.teams)
		teams = _teams_in_stratum(filters, row.currency, row.trust_tier_level, take)
		picked += teams
		detail.append(
			{
				"currency": row.currency,
				"trust_tier_level": row.trust_tier_level,
				"population": row.teams,
				"sampled": len(teams),
				# What one sampled team stands for when the figures are scaled back up.
				"weight": round(row.teams / len(teams), 3) if teams else 0,
			}
		)

	return frappe._dict(teams=picked, population=population, strata=detail, size=len(picked))


def _teams_in_stratum(filters, currency, tier, limit: int) -> list:
	sub = frappe.qb.DocType(_SUBSCRIPTION)
	profile = frappe.qb.DocType("Billing Profile")
	query = (
		frappe.qb.from_(sub)
		.join(profile)
		.on(profile.team == sub.team)
		.select(sub.team)
		.distinct()
		.orderby(sub.team)
		.limit(limit)
	)
	query = query.where(profile.currency == currency) if currency else query.where(
		profile.currency.isnull()
	)
	query = query.where(profile.trust_tier_level == tier) if tier else query.where(
		profile.trust_tier_level.isnull()
	)
	for key in ("country", "collection_mode"):
		if (filters or {}).get(key):
			query = query.where(profile[key] == filters[key])
	return query.run(pluck=True)
