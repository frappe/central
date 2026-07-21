# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The monthly billing run — orchestration only.

`generate.py` drafts one team; `lifecycle.py` settles one invoice. This module
owns everything that spans them: which teams to visit, in what order, and how the
work is spread over workers.
"""

import frappe

from central.billing.revenue.invoicing.generate import generate_team_invoice
from central.billing.revenue.invoicing.lifecycle import open_and_collect

# How many teams / invoices a single orchestrator query pulls back at a time.
PAGE_SIZE = 500


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
	"""
	created = []
	for team in teams_to_bill():
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.generate_team_invoice",
				team=team,
				period_start=period_start,
				period_end=period_end,
			)
			continue
		name = generate_team_invoice(team, period_start, period_end)
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
			limit_page_length=page_size,
		)
		if not page:
			return
		yield from page
		after = page[-1]


def open_drafts(period_end, enqueue: bool = False) -> list[str]:
	"""Phase-2 orchestrator: open every Draft for the billing month."""
	drafts = []
	for inv in drafts_to_settle(period_end):
		drafts.append(inv)
		if enqueue:
			frappe.enqueue("central.billing.revenue.invoicing.open_and_collect", invoice=inv)
		else:
			open_and_collect(inv)
	return drafts


def run_monthly_billing(today=None) -> dict:
	"""Scheduled entrypoint (1st of the month): bill the just-closed calendar month
	end-to-end for every team — the production trigger for the two-phase invoicing
	(#09/#10) that otherwise only ran from demos and tests.

	Phase 1 drafts one consolidated invoice per team for the previous month; phase 2
	opens each Draft and runs the credits-then-card waterfall — settling it, or leaving
	it Open for dunning (#14). Idempotent: drafting is idempotent per (team, period) and
	open_drafts only touches invoices still in Draft, so a retried tick is safe.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	period_start = frappe.utils.get_first_day(today, d_months=-1)
	period_end = frappe.utils.get_last_day(period_start)

	drafted = generate_draft_invoices(period_start, period_end)
	opened = open_drafts(period_end)
	return {
		"period_start": str(period_start),
		"period_end": str(period_end),
		"drafted": len(drafted),
		"opened": len(opened),
	}
