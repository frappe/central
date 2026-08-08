# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Who gets cut off, and when.

The cheap half of the cohort question, and the operationally urgent one. Answering it
needs **no rating at all**: every input is already a fact — invoices that are Open or
Overdue, their real `dunning_starts_on`, and the live ladder. It is `dunning_schedule`
applied to rows that exist.

That makes its cost scale with **delinquency rather than with the book**. Most teams
pay, so the unpaid set stays a few thousand rows at any size of business, and this can
run over everything, on demand, indefinitely. Cohort *revenue* projection has to be
filter-bounded precisely because it cannot make that claim.

Nothing here is estimated and nothing is assumed. Every column is a stored fact or
arithmetic over one.
"""

import frappe

from central.billing.revenue.dunning import dunning_clock_start, dunning_policy, dunning_schedule

# Modes in which nothing is charged off-session — dunning escalates without retrying, so
# a row for one of these teams is asking a human to act rather than waiting on a gateway.
ON_SESSION_MODES = ("Manual Checkout", "Action Required")


def unpaid_invoices(filters: dict | None = None) -> list[frappe._dict]:
	"""Every billable invoice still owing, with what the ladder needs to date it."""
	filters = filters or {}
	conditions = {
		"invoice_type": "Billable",
		"status": ["in", ["Open", "Overdue"]],
		"expected_collection": [">", 0],
	}
	if filters.get("currency"):
		conditions["currency"] = filters["currency"]
	if filters.get("team"):
		conditions["team"] = filters["team"]

	return frappe.get_all(
		"Invoice",
		filters=conditions,
		fields=[
			"name",
			"team",
			"currency",
			"status",
			"due_date",
			"dunning_starts_on",
			"expected_collection",
			"subscription",
		],
		order_by="due_date asc",
		limit_page_length=0,
	)


def rows(on=None, horizon_days: int | None = None, filters: dict | None = None) -> list[dict]:
	"""One row per unpaid invoice: where its ladder has got to, and where it goes next.

	`horizon_days` keeps only the invoices whose next escalation lands inside the window
	— which is how "who is about to be cut off" gets asked without reading the whole
	delinquent book.
	"""
	on = frappe.utils.getdate(on or frappe.utils.nowdate())
	policy = dunning_policy()
	horizon = frappe.utils.add_days(on, horizon_days) if horizon_days else None

	out = []
	for invoice in unpaid_invoices(filters):
		if not invoice.due_date:
			# No due date means no clock; it is a data problem, not a delinquency.
			continue

		clock_start = dunning_clock_start(invoice)
		schedule = dunning_schedule(clock_start, policy)
		reached = [s for s in schedule if frappe.utils.getdate(s.date) <= on]
		ahead = [s for s in schedule if frappe.utils.getdate(s.date) > on]
		next_stage = ahead[0] if ahead else None

		if horizon and next_stage and frappe.utils.getdate(next_stage.date) > horizon:
			continue
		if horizon and not next_stage:
			continue

		mode = _collection_mode(invoice.team)
		out.append(
			{
				"invoice": invoice.name,
				"team": invoice.team,
				"currency": invoice.currency,
				"status": invoice.status,
				"outstanding": invoice.expected_collection,
				"due_date": str(invoice.due_date),
				"clock_starts_on": str(clock_start),
				# A deferred clock means *we* failed to collect on time. Saying so keeps
				# the row from reading as the customer's delinquency.
				"clock_deferred": bool(invoice.dunning_starts_on),
				"days_in": (on - frappe.utils.getdate(clock_start)).days,
				"stage": reached[-1].stage if reached else "Not yet due",
				"next_action": next_stage.stage if next_stage else None,
				"next_action_on": str(next_stage.date) if next_stage else None,
				"suspends_on": _stage_date(schedule, "Suspend"),
				"terminates_on": _stage_date(schedule, "Terminate"),
				"collection_mode": mode,
				"needs_customer_action": mode in ON_SESSION_MODES,
			}
		)

	# Soonest consequence first: the list is read top-down by someone deciding what to
	# do this morning.
	return sorted(out, key=lambda r: (r["suspends_on"] or "9999-12-31", -r["outstanding"]))


def why(invoice: str, on=None) -> dict:
	"""The inverse: given one invoice, why is it at this stage on this date.

	What makes the sweep a debugging tool rather than a list — including whether the
	clock was ever pushed because collection failed on our side.
	"""
	doc = frappe.get_doc("Invoice", invoice)
	on = frappe.utils.getdate(on or frappe.utils.nowdate())
	clock_start = dunning_clock_start(doc)
	schedule = dunning_schedule(clock_start, dunning_policy())

	return {
		"invoice": invoice,
		"team": doc.team,
		"due_date": str(doc.due_date),
		"clock_starts_on": str(clock_start),
		"clock_deferred": bool(doc.dunning_starts_on),
		"deferred_note": (
			"Collection failed on our side, so the escalation clock was pushed forward. "
			"The due date is unchanged — what was owed and when is an accounting fact."
			if doc.dunning_starts_on
			else None
		),
		"days_in": (on - frappe.utils.getdate(clock_start)).days,
		"ladder": [
			{
				"date": str(s.date),
				"stage": s.stage,
				"day": s.day,
				"reached": frappe.utils.getdate(s.date) <= on,
				**({"attempt": s.attempt} if s.get("attempt") else {}),
			}
			for s in schedule
		],
	}


def _stage_date(schedule, stage: str) -> str | None:
	found = next((s for s in schedule if s.stage == stage), None)
	return str(found.date) if found else None


def _collection_mode(team: str) -> str | None:
	return frappe.db.get_value("Billing Profile", team, "collection_mode")
