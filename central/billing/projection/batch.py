# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Projecting a cohort: page it, project each page read-only, persist a scalar row.

The report does not compute. A Frappe query report executes inside the web request, and
this one would have to rate every team in the cohort — at a few thousand teams that is
tens of minutes against a two-minute timeout. It does not degrade; it dies. So a batch
does the work in the background and writes **one scalar row per team**, and the report
becomes an ordinary read like every other report in the module. Per-team detail is never
stored, because it is never needed in bulk — it is computed live for the one team an
operator opens.

Two disciplines keep the work off everyone else's toes:

  * **A read-only transaction per page, not per batch.** InnoDB holds a read-only
    transaction's snapshot for its lifetime, pinning the undo log; one held across a
    whole cohort drags on every other query on the box. A read-only commit costs
    essentially nothing, so the snapshot lives for one page.
  * **Its own queue, and never during the run.** A projection starving the monthly
    billing run of workers on the first of the month is exactly backwards.
"""

import json
import time

import frappe
from frappe import _

from central.billing.projection import behaviour, cohort, engine, outcomes

PROJECTION_QUEUE = "projection"
PAGE_SIZE = 500

# The DocTypes a batch is allowed to write. The engine itself cannot write at all; this
# is the boundary for the persistence that happens afterwards, and it is asserted.
WRITABLE = ("Billing Projection Batch", "Billing Projection Summary")

# How long a batch may run before it stops and reports what it has. A batch that
# overruns is more useful truncated and labelled than left to grind unattended.
WALL_CLOCK_LIMIT_SECONDS = 3600

# Keep a month of batches; a nightly cohort that never prunes is the one component here
# that grows without bound.
RETENTION_DAYS = 30


def projection_queue() -> str:
	"""The projection queue if the bench declares one, else `long` — never `billing`.

	Falling back to the billing queue would be worse than falling back to a slow one:
	it is precisely the contention this separation exists to avoid.
	"""
	from frappe.utils.background_jobs import get_queues_timeout

	if PROJECTION_QUEUE in get_queues_timeout():
		return PROJECTION_QUEUE
	frappe.logger("billing").warning(
		f"no '{PROJECTION_QUEUE}' queue configured (common_site_config workers) — "
		"falling back to 'long'"
	)
	return "long"


def start_sampled(
	filters: dict | None = None, period_start=None, months: int = 1, size: int = 500, today=None
) -> str:
	"""Project a stratified sample instead of the whole cohort.

	The way out of a refusal. The batch records that it was sampled and how big the
	sample was, so every total it produces is labelled as extrapolated wherever it is
	read — an estimate presented as a measurement is worse than no answer.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	drawn = cohort.sample(filters, size)
	if not drawn.teams:
		frappe.throw(_("No teams match this cohort."), frappe.ValidationError)

	batch = frappe.get_doc(
		{
			"doctype": "Billing Projection Batch",
			"as_of": today,
			"period_start": frappe.utils.get_first_day(period_start or today),
			"months": max(1, frappe.utils.cint(months)),
			"batch_state": "Queued",
			"filters": json.dumps(filters or {}, indent=1, sort_keys=True),
			"teams_expected": drawn.size,
			"sampled": 1,
			"sample_size": drawn.size,
			"note": json.dumps({"population": drawn.population, "strata": drawn.strata}, indent=1),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"central.billing.projection.batch.run_batch",
		queue=projection_queue(),
		timeout=WALL_CLOCK_LIMIT_SECONDS + 300,
		batch=batch.name,
		teams=drawn.teams,
	)
	return batch.name


def start(
	filters: dict | None = None, period_start=None, months: int = 1, today=None,
	scenario: str | None = None,
) -> str:
	"""Size the cohort, refuse it if it is too big, and enqueue the batch.

	Raises `CohortTooLargeError` before any team is rated, and `ValidationError` while
	the monthly run still owes work.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	if cohort.run_in_progress(today):
		frappe.throw(
			_("The monthly billing run is still working. Projections wait for it — "
			"one of them is answering a question, the other is billing customers."),
			frappe.ValidationError,
		)

	sizing = cohort.require_within_budget(filters, months)
	batch = frappe.get_doc(
		{
			"doctype": "Billing Projection Batch",
			"as_of": today,
			"period_start": frappe.utils.get_first_day(period_start or today),
			"months": sizing.months,
			"batch_state": "Queued",
			"filters": json.dumps(filters or {}, indent=1, sort_keys=True),
			"teams_expected": sizing.teams,
			"estimated_seconds": sizing.estimated_seconds,
			"scenario": scenario,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"central.billing.projection.batch.run_batch",
		queue=projection_queue(),
		timeout=WALL_CLOCK_LIMIT_SECONDS + 300,
		batch=batch.name,
	)
	return batch.name


def run_batch(batch: str, teams: list | None = None) -> dict:
	"""Work a batch until it is done, aborted, or out of time.

	`teams` is an explicit roster — a sample. Without it the cohort is paged from its
	filters, which is the unbounded-in-memory hazard the paging exists to avoid.
	"""
	doc = frappe.get_doc("Billing Projection Batch", batch)
	filters = json.loads(doc.filters or "{}")
	started = time.monotonic()

	doc.db_set("batch_state", "Running", commit=True)
	doc.db_set("started_at", frappe.utils.now(), commit=True)

	projected = 0
	partial = False
	pages = (
		[(None, None, teams[i : i + PAGE_SIZE]) for i in range(0, len(teams), PAGE_SIZE)]
		if teams
		else cohort.pages(filters, PAGE_SIZE)
	)
	for _after, _until, page in pages:
		if time.monotonic() - started > WALL_CLOCK_LIMIT_SECONDS:
			partial = True
			break
		projected += _project_page(doc, page)
		doc.db_set("teams_projected", projected, commit=True)

	doc.db_set("batch_state", "Partial" if partial else "Complete", commit=True)
	doc.db_set("completed_at", frappe.utils.now(), commit=True)
	if partial:
		doc.db_set(
			"note",
			f"Stopped after {WALL_CLOCK_LIMIT_SECONDS}s with {projected} of "
			f"{doc.teams_expected} teams projected. The rows below are real; the cohort "
			"is incomplete.",
			commit=True,
		)
	return {"batch": batch, "teams_projected": projected, "status": doc.batch_state}


def _project_page(batch_doc, teams: list) -> int:
	"""Project one page inside its own read-only transaction, then persist outside it.

	The two halves are deliberately separate. The engine cannot write — that is a
	database guarantee, not a convention — so the rows it produces are handed back as
	plain data and written afterwards in an ordinary transaction.
	"""
	rows, failures = [], []
	for team in teams:
		try:
			rows.append(_summarise(team, batch_doc))
		except Exception:
			# One bad team must not take the cohort down — the same containment the
			# billing run gives a failing team. The failure is *held*, not logged here:
			# writing an Error Log mid-page leaves the transaction dirty, and the next
			# team's projection then refuses to start. Containment that cascades is not
			# containment; it turns one bad team into a lost page.
			failures.append((team, frappe.get_traceback()))

	for row in rows:
		frappe.get_doc(row).insert(ignore_permissions=True)
	frappe.db.commit()

	for team, traceback in failures:
		frappe.log_error(
			title="Billing Projection Failure",
			message=f"team: {team}\n\n{traceback}",
			reference_doctype="Billing Projection Batch",
			reference_name=batch_doc.name,
		)
	if failures:
		frappe.db.commit()
	return len(rows)


def _summarise(team: str, batch_doc) -> dict:
	"""One team's projected position, flattened to scalars the report can read."""
	if batch_doc.scenario:
		return _summarise_under_scenario(team, batch_doc)
	return _summarise_live(team, batch_doc)


def _summarise_under_scenario(team: str, batch_doc) -> dict:
	"""Project this team as the scenario pretends, so a batch can be a what-if.

	Two batches over the same teams — one live, one under a scenario — are what the
	blast radius compares. Without this a scenario could only ever be asked about one
	team at a time, which is not the question anyone has before shipping a change.
	"""
	from central.billing import settings
	from central.billing.catalog import pricing

	doc = frappe.get_doc("Billing Scenario", batch_doc.scenario)
	with settings.overridden(**doc.overrides()), pricing.overridden_rates(
		doc.rate_overrides_applied()
	):
		return _summarise_live(team, batch_doc)


def _summarise_live(team: str, batch_doc) -> dict:
	months = frappe.utils.cint(batch_doc.months) or 1
	if months > 1:
		projection = engine.project_months(
			team, batch_doc.period_start, months=months, today=batch_doc.as_of
		)
		first = next((m for m in projection["months"] if m["invoice"]), None)
		invoice = first["invoice"] if first else None
		calendar = first["calendar"] if first else None
		outcome = first["outcome"] if first else None
		ends = projection["ends"]
		suspends_on = ends.get("suspended_on")
		currency = projection["currency"]
		credit_balance = ends.get("balance")
		shortfall = sum(
			frappe.utils.flt((m.get("settlement") or {}).get("shortfall"))
			for m in projection["months"]
		)
	else:
		period_end = frappe.utils.get_last_day(batch_doc.period_start)
		projection = engine.project(
			team, batch_doc.period_start, period_end, today=batch_doc.as_of
		)
		invoice = projection["invoice"]
		calendar = projection["calendar"]
		outcome = projection["outcome"]
		currency = projection["currency"]
		credit_balance = None
		suspends_on = _suspends_on(calendar, outcome)
		shortfall = None

	findings = (outcome or {}).get("findings") or []
	return {
		"doctype": "Billing Projection Summary",
		"batch": batch_doc.name,
		"team": team,
		"currency": currency,
		"as_of": batch_doc.as_of,
		"projected_total": (invoice or {}).get("total"),
		"measured": (invoice or {}).get("measured"),
		"estimated": (invoice or {}).get("estimated"),
		"credit_balance": credit_balance,
		"shortfall": shortfall,
		"settles_via": _settles_via(team),
		"outcome": _outcome_label(outcome, findings),
		"outcome_reason": findings[0]["summary"] if findings else None,
		"due_on": (calendar or {}).get("due_on"),
		"suspends_on": suspends_on,
		"paid_on_time": _paid_on_time(team, batch_doc.as_of),
	}


def _suspends_on(calendar, outcome):
	"""The date the ladder reaches suspension, but only where non-payment is entailed.

	Printing a suspension date against a team we have no reason to think will miss is
	how a report teaches people to ignore it.
	"""
	if not calendar or not outcome or outcome.get("entailed_branch") != "if_never_paid":
		return None
	stage = next(
		(s for s in calendar.get("if_never_paid", []) if s["stage"] == "Suspend"), None
	)
	return stage["date"] if stage else None


def _outcome_label(outcome, findings) -> str:
	if not outcome:
		return "Nothing billable"
	if outcome.get("mode") != outcomes.DERIVED:
		return outcome.get("mode")
	return findings[0]["summary"] if findings else "No obstacle found"


def _paid_on_time(team: str, on) -> str:
	""""6 / 6" beside a failure points at us; "3 / 6" points at them."""
	record = behaviour.summary(team, on=on)
	return f"{record['on_time']} / {record['invoices']}" if record["invoices"] else "—"


def _settles_via(team: str) -> str:
	from central.billing.payments import collection

	methods = collection.ordered_methods(team)
	if methods:
		return frappe.db.get_value("Payment Method", methods[0].name, "method_type") or "Method"
	return "Credits only"


def prune(days: int = RETENTION_DAYS) -> int:
	"""Drop batches past the retention window, and their rows with them.

	A nightly cohort that never prunes is the one part of this that grows without
	bound, so the sweep is scheduled rather than remembered.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -days)
	stale = frappe.get_all(
		"Billing Projection Batch", filters={"creation": ["<", cutoff]}, pluck="name"
	)
	for name in stale:
		frappe.db.delete("Billing Projection Summary", {"batch": name})
		frappe.delete_doc("Billing Projection Batch", name, force=True, ignore_permissions=True)
	frappe.db.commit()
	return len(stale)


def compare_batches(live: str, altered: str) -> dict:
	"""How far a change reaches, measured across two batches of the same teams.

	This is what `blast` is for. Both sides have to be real projections over the same
	cohort, or the difference between them is not attributable to the change.
	"""
	from central.billing.projection import blast

	live_doc = frappe.get_doc("Billing Projection Batch", live)
	altered_doc = frappe.get_doc("Billing Projection Batch", altered)

	comparison = blast.compare_rows(_rows_of(live), _rows_of(altered))
	summary = blast.summarise(
		comparison,
		sampled=bool(altered_doc.sampled or live_doc.sampled),
		sample_size=frappe.utils.cint(altered_doc.sample_size),
		population=frappe.utils.cint(altered_doc.teams_expected),
	)
	return {
		"live_batch": live,
		"altered_batch": altered,
		"scenario": altered_doc.scenario,
		"summary": summary,
		"headline": blast.describe(summary),
		"newly_suspending": comparison["newly_suspending"],
		"newly_short": comparison["newly_short"],
		"suspension_moved_earlier": comparison["suspension_moved_earlier"],
	}


def _rows_of(batch: str) -> list[dict]:
	return frappe.get_all(
		"Billing Projection Summary",
		filters={"batch": batch},
		fields=["team", "currency", "projected_total", "shortfall", "suspends_on"],
		limit_page_length=0,
	)
