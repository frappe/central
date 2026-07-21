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


def generate_draft_invoices(period_start, period_end, enqueue: bool = False) -> list[str]:
	"""Phase-1 orchestrator: ONE consolidated draft per team for the period.

	A team that runs instances across several clusters still gets a single
	invoice (generate_team_invoice aggregates all its clusters). The team's first
	subscription is the primary (its payment method funds the auto-charge).
	"""
	primary = {}
	for s in frappe.get_all("Subscription", fields=["name", "team"], order_by="creation asc"):
		primary.setdefault(s.team, s.name)
	created = []
	for team, sub in primary.items():
		if enqueue:
			frappe.enqueue(
				"central.billing.revenue.invoicing.generate_team_invoice",
				team=team,
				period_start=period_start,
				period_end=period_end,
				subscription=sub,
			)
			continue
		name = generate_team_invoice(team, period_start, period_end, subscription=sub)
		if name:
			created.append(name)
	return created


def open_drafts(period_end, enqueue: bool = False) -> list[str]:
	"""Phase-2 orchestrator: open every Draft for the billing month."""
	drafts = frappe.get_all(
		"Invoice", filters={"status": "Draft", "period_end": period_end}, pluck="name"
	)
	for inv in drafts:
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
