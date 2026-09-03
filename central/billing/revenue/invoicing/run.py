# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The monthly billing run — orchestration only.

`generate.py` drafts one team; `lifecycle.py` settles one invoice. This module
owns everything that spans them: which teams to visit, in what order, and how the
work is spread over workers.
"""

import random
import time

import frappe
from frappe.query_builder.functions import Count

from central.billing.doctype.billing_run.billing_run import snapshot
from central.billing.platform import metrics
from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.invoicing.lifecycle import open_and_collect

# How many teams / invoices one page job is responsible for.
PAGE_SIZE = 500

# Collection pages are smaller than drafting pages: each invoice is a gateway
# round-trip (~2s) rather than local arithmetic (~0.3s), and a page has to finish
# inside its queue timeout.
COLLECT_PAGE_SIZE = 100

# The monthly run gets its own queue, not `long`. It is not a daily job sharing a
# pool with everything else: its worker count is the throughput knob (how many
# teams are billed at once) AND the gateway concurrency cap (how many charges are
# in flight at once). Both need to be tuned for billing alone, and a saturated
# billing run must not starve the rest of the site. Configure it in
# common_site_config.json — the worker count is the number that matters:
#
#   "workers": {"billing": {"timeout": 3000, "background_workers": 8}}
#
# and give the queue a worker (`bench worker --queue billing`).
BILLING_QUEUE = "billing"


# Every unit failure is logged under this one title, so an operator (and
# `billing_run_status`) can count a run's casualties with a single filter.
BILLING_RUN_FAILURE = "Billing Run Failure"

_SAVEPOINT = "billing_run_unit"

# Drafting is the phase with a *global* lock in it: every Invoice insert takes the
# `tabSeries` row for its number and holds it until commit, so every worker in the
# run queues behind the same row for a few milliseconds. Nearly always invisible;
# under a slow disk or a long page it surfaces as a lock-wait timeout (1205) or a
# deadlock (1213). Containing those like a data error would be wrong — the team is
# fine, it just lost a race — and the draft tick only comes round once a MONTH, so
# a contained loser stays unbilled until someone notices. Retry instead.
_CONTENTION = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)
CONTENTION_RETRIES = 4
CONTENTION_BACKOFF = 0.1  # seconds; scaled by attempt, plus jitter


def billing_queue() -> str:
	"""The billing queue if the bench declares one, else `long`.

	Enqueuing to a queue nobody consumes is silent death — the jobs sit in redis and
	the month simply never gets billed. A bench that hasn't configured the billing
	worker yet falls back to a queue that definitely has one, loudly.
	"""
	from frappe.utils.background_jobs import get_queues_timeout

	if BILLING_QUEUE in get_queues_timeout():
		return BILLING_QUEUE
	frappe.logger("billing").warning(
		f"no '{BILLING_QUEUE}' queue configured (common_site_config workers) — falling back to 'long'"
	)
	return "long"


def _contain(unit: str, doctype: str, name: str, error: Exception, undo: bool) -> None:
	"""Contain one unit's failure so the run survives it — or refuse to.

	Order matters. The **file log** is written first and unconditionally, because it
	is the only record that survives a transaction that never commits: "why was this
	team not billed?" has to be answerable after a crash, not only after a tidy
	failure. The Error Log row is the queryable copy (`billing_run_status` counts
	it), but it is a database write like any other — a run whose worker is killed
	before its commit keeps the file line and loses the row.

	Then the judgement call. A savepoint exists only inside a live transaction: if
	the database restarted, the connection dropped, or something in the unit
	committed underneath us, `ROLLBACK TO SAVEPOINT` fails. That is not a bad team —
	it is the machinery being broken, and swallowing it would convert one outage
	into a silent run where every remaining team merely "wasn't billed". So the
	original error is re-raised: the job dies, RQ records it, and the tick is
	re-fired once the database is back.
	"""
	frappe.logger("billing").error(f"{BILLING_RUN_FAILURE}: {unit}", exc_info=error)
	if undo:
		try:
			frappe.db.rollback(save_point=_SAVEPOINT)
		except Exception as rollback_failed:
			raise error from rollback_failed
	frappe.log_error(
		title=BILLING_RUN_FAILURE,
		message=f"{unit}\n\n{frappe.get_traceback()}",
		reference_doctype=doctype,
		reference_name=name,
	)


def _tally(counters: dict | None, key: str) -> None:
	"""Bump one run counter, if the caller is keeping any."""
	if counters is not None:
		counters[key] = counters.get(key, 0) + 1


def draft_team_invoice(team: str, period_start, period_end, counters: dict | None = None) -> list[str]:
	"""Draft one team's invoice — the unit of work phase 1 fans out.

	One team = one transaction = one commit, on every path. Failure is contained to
	the team: a missing rate or a broken tax profile must not take the other
	999,999 teams' invoices with it. The savepoint undoes only this team's writes,
	so a caller part-way through a page keeps the teams it already billed.

	A contained failure is not re-raised, and needn't be: drafting is idempotent per
	(team, period), so re-running the phase retries exactly the teams that failed.
	A partial run is resumable for free.

	Lock contention is not a failure at all, though, and is retried here rather than
	contained — see `_CONTENTION`. InnoDB has already rolled the transaction back by
	the time we see it, which is safe precisely because the caller commits per team:
	the rollback can only ever discard this one team's work.
	"""
	unit = f"Drafting {team} for {period_start}..{period_end}"
	for attempt in range(CONTENTION_RETRIES):
		frappe.db.savepoint(_SAVEPOINT)
		try:
			name = generate_team_invoice(team, period_start, period_end)
			return [name] if name else []
		except _CONTENTION as error:
			frappe.db.rollback()
			if attempt == CONTENTION_RETRIES - 1:
				# Out of patience: record it and let the next tick pick the team up.
				_contain(unit, "Team", team, error, undo=False)
				_tally(counters, "failed")
				return []
			# Jittered, so a whole page of retriers doesn't re-collide in lockstep.
			time.sleep(CONTENTION_BACKOFF * (attempt + 1) + random.uniform(0, CONTENTION_BACKOFF))
		except Exception as error:
			_contain(unit, "Team", team, error, undo=True)
			_tally(counters, "failed")
			return []


def settle_draft(invoice: str, counters: dict | None = None) -> dict | None:
	"""Open + collect one invoice — the unit of work phase 2 fans out.

	Nothing is undone here, unlike drafting: by ADR 0017 the charge leg commits its
	`Initiated` Payment Attempt *before* calling the gateway, precisely so a crash
	leaves a durable claim. Rolling that back would be undoing the safety. A failed
	unit is logged and left where it is — `run_reconciliation` asks the gateway what
	really happened, and dunning picks up whatever stayed Open.
	"""
	try:
		return open_and_collect(invoice)
	except Exception as error:
		_contain(f"Settling {invoice}", "Invoice", invoice, error, undo=False)
		_tally(counters, "failed")
		# The run broke down over this invoice; the customer is not late because we
		# are. Their retry ladder restarts from a date we actually asked on.
		from central.billing.revenue.dunning import defer_dunning

		defer_dunning(invoice, f"collection failed in the run: {type(error).__name__}")
		return None


def team_pages(page_size: int = PAGE_SIZE):
	"""Yield the teams holding a subscription, one bounded page at a time.

	The orchestrator must not hold the whole subscription table in memory — at a
	million teams that is the run's first bottleneck. Keyset paging (`team > last
	seen`, ordered) walks the `Subscription(team)` index in fixed-size pages, so
	memory is flat in team count.
	"""
	sub = frappe.qb.DocType("Subscription")
	after = ""
	while True:
		page = (
			frappe.qb.from_(sub)
			.select(sub.team)
			.distinct()
			.where(sub.team > after)
			.orderby(sub.team)
			.limit(page_size)
		).run(pluck=True)
		if not page:
			return
		yield page
		after = page[-1]


def teams_to_bill(page_size: int = PAGE_SIZE):
	"""Every team holding a subscription, page by page, flattened."""
	for page in team_pages(page_size):
		yield from page


def teams_in_range(after: str, until: str) -> list[str]:
	"""The teams in one cursor slice `(after, until]` — a page job's whole workload.

	The slice is re-derived from the bounds rather than carried as a list of names:
	the job argument stays two strings whatever the page size, and a team created
	inside the slice after the tick read it is picked up rather than skipped.
	"""
	sub = frappe.qb.DocType("Subscription")
	return (
		frappe.qb.from_(sub)
		.select(sub.team)
		.distinct()
		.where((sub.team > after) & (sub.team <= until))
		.orderby(sub.team)
	).run(pluck=True)


def draft_team_page(after: str, until: str, period_start, period_end) -> dict:
	"""Draft every team in one cursor slice — the unit a billing worker picks up.

	Committing per team is the point of the loop: one team = one transaction = one
	commit, so a page job killed at team 300 of 500 keeps the 299 it finished, and
	re-running the page skips them (drafting is idempotent per (team, period)).
	The page is the unit of *scheduling*; the team is still the unit of *work*.
	"""
	with metrics.timed("billing.draft_page", period_end=str(period_end)) as counters:
		counters.update(drafted=0, skipped=0, failed=0)
		for team in teams_in_range(after, until):
			before = counters["failed"]
			if draft_team_invoice(team, period_start, period_end, counters):
				counters["drafted"] += 1
			elif counters["failed"] == before:
				# Nothing to bill this team for — not a failure, just an empty month.
				counters["skipped"] += 1
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one team, one transaction
		return {"after": after, "until": until, **counters}


def generate_draft_invoices(period_start, period_end, enqueue: bool = False) -> list[str]:
	"""Phase-1 orchestrator: one consolidated draft invoice per team.

	A team that runs instances across several clusters still gets a single
	consolidated invoice (generate_team_invoice aggregates all its clusters), broken
	out by Project on its own line items, not by separate invoices.

	With `enqueue` the orchestrator rates nothing itself, and — just as important —
	enqueues nothing per team. It hands out **page jobs**: at a million teams, a
	job-per-team tick is a million redis round-trips, which neither finishes inside
	a scheduler timeout nor fits in redis. Two thousand page jobs do both. How many
	run at once is the billing queue's worker count, which is also the number of
	gateway calls phase 2 can have in flight — one knob, set by ops, not by code.

	Returns the invoices drafted (inline) or the page bounds fanned out (enqueue).
	"""
	created = []
	after = ""
	for page in team_pages():
		until = page[-1]
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.draft_team_page",
				queue=billing_queue(),
				job_id=f"billing-draft::{period_end}::{until}",
				deduplicate=True,
				after=after,
				until=until,
				period_start=period_start,
				period_end=period_end,
			)
			created.append(until)
			after = until
			continue
		for team in page:
			created.extend(draft_team_invoice(team, period_start, period_end))
			# Inline or fanned out, a team is a transaction. It bounds what a
			# contention rollback can discard, and it stops the run holding the
			# `tabSeries` row (taken by every Invoice insert) for a whole page —
			# which is how one slow run becomes everyone else's lock-wait timeout.
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one team, one transaction
	return created


def draft_pages(cutoff, page_size: int = COLLECT_PAGE_SIZE):
	"""Yield every still-Draft invoice for a month that closed on or before `cutoff`,
	one bounded page at a time.

	`<=`, not `==`: collection sweeps every draft whose period has ended, not one exact
	month. That is what makes the sweep re-runnable — a draft that landed after the last
	sweep (drafting hadn't caught up), or one a settle page left behind, is found by the
	next sweep instead of being orphaned until (and then past) the next monthly tick.

	Keyset paging on the name — correct even though settling a draft removes it
	from the filter as we walk, because the cursor advances by name, not by offset.
	"""
	after = ""
	while True:
		page = frappe.get_all(
			"Invoice",
			filters={"status": "Draft", "period_end": ("<=", cutoff), "name": (">", after)},
			pluck="name",
			order_by="name asc",
			limit=page_size,
		)
		if not page:
			return
		yield page
		after = page[-1]


def drafts_to_settle(cutoff, page_size: int = COLLECT_PAGE_SIZE):
	"""Every settleable Draft on or before `cutoff`, page by page, flattened."""
	for page in draft_pages(cutoff, page_size):
		yield from page


def drafts_in_range(cutoff, after: str, until: str) -> list[str]:
	"""The still-Draft invoices in one cursor slice `(after, until]`, for any month
	that closed on or before `cutoff`.

	Re-read at run time, not carried in the job: by the time a page job starts, some
	of its slice may already be settled (a retried tick, a customer paying
	on-session), and those must not be touched again.
	"""
	return frappe.get_all(
		"Invoice",
		filters=[
			["status", "=", "Draft"],
			["period_end", "<=", cutoff],
			["name", ">", after],
			["name", "<=", until],
		],
		pluck="name",
		order_by="name asc",
	)


def settle_draft_page(cutoff, after: str, until: str) -> dict:
	"""Settle every draft in one cursor slice — the unit a billing worker picks up.

	Sequential within the page, deliberately: the gateway concurrency of the whole
	run is the number of billing workers, and that is the only thing standing
	between a million-invoice month and a wall of 429s. Widening the page would not
	make it faster — it would make it rate-limited.
	"""
	with metrics.timed("billing.settle_page", cutoff=str(cutoff)) as counters:
		counters.update(settled=0, failed=0)
		for invoice in drafts_in_range(cutoff, after, until):
			if settle_draft(invoice, counters):
				counters["settled"] += 1
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one invoice, one transaction
		return {"after": after, "until": until, **counters}


def open_drafts(cutoff, enqueue: bool = False) -> list[str]:
	"""Phase-2 orchestrator: open every Draft for a month closed on or before `cutoff`.

	Page jobs, not a job per invoice — same reason as drafting, plus one specific to
	collection: a job per invoice puts the run's gateway concurrency at the mercy of
	how many workers happen to be free. A page job holds its invoices and works them
	in order, so in-flight charges never exceed the billing worker count.

	Claiming Draft -> Open under a row lock already makes two workers on one invoice
	harmless; the deduplicated page job id keeps them from queueing at all. Because a
	settled draft drops out of the scan, re-running this against the same cutoff only
	ever picks up what is still owed — which is exactly what the daily sweep relies on.
	"""
	drafts = []
	after = ""
	for page in draft_pages(cutoff):
		until = page[-1]
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.settle_draft_page",
				queue=billing_queue(),
				job_id=f"billing-settle::{cutoff}::{until}",
				deduplicate=True,
				cutoff=cutoff,
				after=after,
				until=until,
			)
			drafts.append(until)
			after = until
			continue
		for invoice in page:
			drafts.append(invoice)
			settle_draft(invoice)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one invoice, one transaction
	return drafts


def billing_period(today=None) -> tuple:
	"""The calendar month that just closed — the period a run on `today` bills."""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(today, d_months=-1)
	return period_start, frappe.utils.get_last_day(period_start)


def draft_monthly_invoices(today=None) -> dict:
	"""Tick 1 (1st, off-peak): draft the just-closed month, one job per team.

	Drafting and collection are separate ticks, not one job that does both: rating is
	heavy and local, collection is slow and external, and a run that interleaves them
	can only go as fast as its slowest gateway call.

	Drafting fires once, on the 1st — not the 28th — because a month billed in arrears
	is not closed until it ends; drafting on the 28th would bill days that had not
	happened yet. Collection does not run a fixed few hours later hoping drafting is
	done: it is a daily sweep (`collect_due_invoices`) that drains whatever has drafted,
	so a run that overruns the day is finished by the next sweep, not abandoned.
	"""
	period_start, period_end = billing_period(today)
	snapshot(billing_run_status(today), "Drafting")
	fanned = generate_draft_invoices(period_start, period_end, enqueue=True)
	metrics.emit("billing.draft_tick", period_end=str(period_end), pages=len(fanned))
	return {"period_start": str(period_start), "period_end": str(period_end), "pages": len(fanned)}


def collect_due_invoices(today=None) -> dict:
	"""Tick 2 (daily): open + collect every Draft whose month has already closed.

	Daily, not a single tick a fixed few hours after drafting: at a million teams the
	draft page jobs may still be finishing when collection first fires, and a one-shot
	scan would collect only the drafts that existed at that instant and orphan every one
	that landed later. Nor is there a second monthly pass to catch them — the tick comes
	round once, pinned to one exact period.

	So collection is a daily sweep of `period_end <= the just-closed month`. It re-runs
	until nothing is owed: drafts that appeared after the previous sweep get collected on
	the next one, and a draft a settle page left behind — this month's or an older run's
	— is swept up rather than stranded. Once the run has drained it is a cheap indexed
	no-op (no Draft for a closed period left to find).

	`open_drafts` skips anything already Open/Paid, so re-firing never double-charges;
	`settle_draft` defers dunning on failure, so a slow sweep never makes a customer late.
	"""
	_, period_end = billing_period(today)
	# Recorded before fanning out, so the record of what the run has achieved (and what it
	# still owes) exists even if collection then falls over.
	status = billing_run_status(today)
	metrics.emit("billing.run_status", **status)
	# Only claim to be collecting when something is owed, so a period that finished
	# does not flip Complete -> Collecting -> Complete on every later sweep.
	snapshot(status, "Collecting" if status["pending_collection"] else None)
	fanned = open_drafts(period_end, enqueue=True)
	metrics.emit("billing.collect_tick", period_end=str(period_end), pages=len(fanned))
	# Re-derived after the sweep has been handed out: nothing owed means the period is done.
	done = billing_run_status(today)
	snapshot(done, "Complete" if not done["pending_collection"] else None)
	return {"period_end": str(period_end), "pages": len(fanned)}


def billing_run_status(today=None) -> dict:
	"""What the run for the just-closed month has actually achieved so far.

	Derived from the tables, not tracked alongside them: a counter the run keeps is a
	counter that lies the moment a worker dies mid-job. Teams, invoices and their
	statuses are the truth, so this reads correctly for a run that only half
	happened — which is the run you need to read. `pending_draft` and
	`pending_collection` are what a re-fired tick would pick up.

	`pending_draft` is an upper bound: a team with nothing billable produces no
	invoice by design, and shows up here as one that was never drafted.
	"""
	period_start, period_end = billing_period(today)
	sub = frappe.qb.DocType("Subscription")
	teams = (frappe.qb.from_(sub).select(Count(sub.team).distinct())).run()[0][0]

	inv = frappe.qb.DocType("Invoice")
	counts = {
		row.status: row.invoices
		for row in (
			frappe.qb.from_(inv)
			.select(inv.status, Count(inv.name).as_("invoices"))
			.where(inv.period_end == period_end)
			.groupby(inv.status)
		).run(as_dict=True)
	}
	drafted = sum(n for status, n in counts.items() if status != "Cancelled")
	pending_collection = counts.get("Draft", 0)
	return {
		"period_start": str(period_start),
		"period_end": str(period_end),
		"teams": teams,
		"drafted": drafted,
		"pending_draft": max(teams - drafted, 0),
		"pending_collection": pending_collection,
		"collected": drafted - pending_collection,
		"by_status": counts,
		"failures": frappe.db.count(
			"Error Log", {"method": BILLING_RUN_FAILURE, "creation": [">=", period_end]}
		),
	}


def run_monthly_billing(today=None) -> dict:
	"""Bill the just-closed month end-to-end, inline — the manual/demo/test path.

	The scheduler runs the two ticks above instead. This stays as the one-call
	version for a small site, a demo, or an operator re-running a period by hand:
	same work, same idempotency, no workers involved.
	"""
	period_start, period_end = billing_period(today)
	drafted = generate_draft_invoices(period_start, period_end)
	opened = open_drafts(period_end)
	return {
		"period_start": str(period_start),
		"period_end": str(period_end),
		"drafted": len(drafted),
		"opened": len(opened),
	}
