# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The monthly billing run — orchestration only.

`generate.py` drafts one team; `lifecycle.py` settles one invoice. This module
owns everything that spans them: which teams to visit, in what order, and how the
work is spread over workers.
"""

import frappe
from frappe.query_builder.functions import Count

from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.invoicing.lifecycle import open_and_collect

# How many teams / invoices a single orchestrator query pulls back at a time.
PAGE_SIZE = 500

# Billing units are minutes-long and gateway-bound; they belong on the long queue,
# away from the short jobs a user is waiting on.
BILLING_QUEUE = "long"

# Every unit failure is logged under this one title, so an operator (and
# `billing_run_status`) can count a run's casualties with a single filter.
BILLING_RUN_FAILURE = "Billing Run Failure"

_SAVEPOINT = "billing_run_unit"


def draft_team_invoice(team: str, period_start, period_end) -> str | None:
	"""Draft one team's invoice — the unit of work phase 1 fans out.

	One team = one job = one transaction = one commit. Failure is contained to the
	team: a missing rate or a broken tax profile must not take the other 49,999
	teams' invoices with it. The savepoint undoes only this team's writes — the
	inline path bills many teams in one transaction, so a blanket rollback here
	would discard the teams already billed.

	Nothing is re-raised, and nothing needs to be: drafting is idempotent per
	(team, period), so re-running the phase retries exactly the teams that failed.
	A partial run is resumable for free.
	"""
	frappe.db.savepoint(_SAVEPOINT)
	try:
		return generate_team_invoice(team, period_start, period_end)
	except Exception:
		frappe.db.rollback(save_point=_SAVEPOINT)
		frappe.log_error(
			title=BILLING_RUN_FAILURE,
			message=f"Drafting {team} for {period_start}..{period_end}\n\n{frappe.get_traceback()}",
			reference_doctype="Team",
			reference_name=team,
		)
		return None


def settle_draft(invoice: str) -> dict | None:
	"""Open + collect one invoice — the unit of work phase 2 fans out.

	No savepoint here, unlike drafting: by ADR 0017 the charge leg commits its
	`Initiated` Payment Attempt *before* calling the gateway, precisely so a crash
	leaves a durable claim. Undoing that would be undoing the safety. A failed unit
	is logged and left where it is — `run_reconciliation` asks the gateway what
	really happened, and dunning picks up whatever stayed Open.
	"""
	try:
		return open_and_collect(invoice)
	except Exception:
		frappe.log_error(
			title=BILLING_RUN_FAILURE,
			message=f"Settling {invoice}\n\n{frappe.get_traceback()}",
			reference_doctype="Invoice",
			reference_name=invoice,
		)
		return None


def teams_to_bill(page_size: int = PAGE_SIZE):
	"""Yield every team holding a subscription, one page at a time.

	The orchestrator must not hold the whole subscription table in memory — at 50k
	teams that is the run's first bottleneck. Keyset paging (`team > last seen`,
	ordered) walks the `Subscription(team)` index in bounded pages and hands teams
	out as it reads them, so memory is flat in team count.
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
		yield from page
		after = page[-1]


def generate_draft_invoices(period_start, period_end, enqueue: bool = False) -> list[str]:
	"""Phase-1 orchestrator: ONE consolidated draft per team for the period.

	A team that runs instances across several clusters still gets a single
	invoice (generate_team_invoice aggregates all its clusters, and picks the
	team's oldest subscription as the primary that funds the auto-charge).

	With `enqueue` the orchestrator rates nothing itself: it pages the teams and
	fans one job out per team, so the run scales with workers rather than with the
	length of one scheduler tick. The job id is (period, team) and deduplicated —
	a tick that fires twice, or overlaps a manual run, queues each team once.

	Returns the invoices drafted (inline) or the teams fanned out (enqueue).
	"""
	created = []
	for team in teams_to_bill():
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.draft_team_invoice",
				queue=BILLING_QUEUE,
				job_id=f"billing-draft::{period_end}::{team}",
				deduplicate=True,
				team=team,
				period_start=period_start,
				period_end=period_end,
			)
			created.append(team)
			continue
		name = draft_team_invoice(team, period_start, period_end)
		if name:
			created.append(name)
	return created


def drafts_to_settle(period_end, page_size: int = PAGE_SIZE):
	"""Yield the period's Draft invoices, one page at a time.

	Keyset paging on the name, so it stays bounded at 50k invoices — and correct
	even though settling a draft removes it from the filter as we walk.
	"""
	after = ""
	while True:
		page = frappe.get_all(
			"Invoice",
			filters={"status": "Draft", "period_end": period_end, "name": (">", after)},
			pluck="name",
			order_by="name asc",
			limit=page_size,
		)
		if not page:
			return
		yield from page
		after = page[-1]


def open_drafts(period_end, enqueue: bool = False) -> list[str]:
	"""Phase-2 orchestrator: open every Draft for the billing month.

	One job per invoice, deduplicated on the invoice — collection is where the
	gateway round-trips are, so this is the phase that must not be one long
	sequential tick. Claiming Draft -> Open under a row lock already makes two
	workers on one invoice harmless; the job id keeps them from queueing at all.
	"""
	drafts = []
	for inv in drafts_to_settle(period_end):
		drafts.append(inv)
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.settle_draft",
				queue=BILLING_QUEUE,
				job_id=f"billing-settle::{inv}",
				deduplicate=True,
				invoice=inv,
			)
		else:
			settle_draft(inv)
	return drafts


def billing_period(today=None) -> tuple:
	"""The calendar month that just closed — the period a run on `today` bills."""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(today, d_months=-1)
	return period_start, frappe.utils.get_last_day(period_start)


def draft_monthly_invoices(today=None) -> dict:
	"""Tick 1 (1st, off-peak): draft the just-closed month, one job per team.

	The two phases are separate scheduler ticks, not one job that does both: rating
	is heavy and local, collection is slow and external, and a run that interleaves
	them can only go as fast as its slowest gateway call.

	They are hours apart on the same day rather than the 28th and the 1st, because a
	calendar month billed in arrears is not closed until it ends — drafting on the
	28th would bill days that had not happened yet.
	"""
	period_start, period_end = billing_period(today)
	fanned = generate_draft_invoices(period_start, period_end, enqueue=True)
	frappe.logger("billing").info(f"billing run {period_end}: drafting fanned out for {len(fanned)} teams")
	return {"period_start": str(period_start), "period_end": str(period_end), "teams": len(fanned)}


def collect_monthly_invoices(today=None) -> dict:
	"""Tick 2 (1st, once drafting has settled): open + collect, one job per invoice.

	Whatever tick 1 failed to draft simply isn't here yet; it is picked up by the
	next run rather than blocking this one, and the invoices that did draft still
	get collected on time.
	"""
	period_start, period_end = billing_period(today)
	# Logged before fanning out, so the record of what drafting achieved (and what it
	# missed) exists even if collection then falls over.
	frappe.logger("billing").info(f"billing run {period_end}: {billing_run_status(today)}")
	fanned = open_drafts(period_end, enqueue=True)
	frappe.logger("billing").info(f"billing run {period_end}: collection fanned out for {len(fanned)} invoices")
	return {"period_start": str(period_start), "period_end": str(period_end), "invoices": len(fanned)}


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
