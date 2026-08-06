# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What billing will do to one team, next period.

The engine does not model billing. It calls the same two decision functions the
monthly run calls — `rate_team_period` to price the period and `dunning_schedule` to
lay out the escalation ladder — and stops before the effects. Whatever the run would
charge, this reports; whatever the run would do about non-payment, this dates.

Two things it deliberately does not do. It never asserts whether a card will succeed,
so the collection calendar is given as *both* branches: settled on the due date, and
the full ladder if nothing is ever paid. And it never writes, which is a database
guarantee rather than a convention — see `guard`.
"""

import frappe

from central.billing import settings
from central.billing.projection import estimate
from central.billing.projection.basis import MEASURED, mark, split_totals
from central.billing.projection.guard import read_only
from central.billing.revenue.dunning import dunning_clock_start, dunning_policy, dunning_schedule
from central.billing.revenue.invoicing.generate import rate_team_period, team_clusters


def project(
	team: str,
	period_start,
	period_end,
	today=None,
	recorder=None,
	source=None,
) -> dict:
	"""Project one team over one period. Reads only; returns plain data.

	`recorder` and `source` are the record-and-replay seam: a recorder captures every
	read so the projection can later be replayed against frozen inputs, and a source
	answers reads from such a recording instead of the database. Both are accepted and
	unused here so that adding the regression harness does not have to reshape the
	engine.
	"""
	with read_only():
		return _project(team, period_start, period_end, today)


def _project(team: str, period_start, period_end, today=None) -> dict:
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	start = frappe.utils.getdate(period_start)
	end = frappe.utils.getdate(period_end)

	metered = estimate.metered_lines(team, team_clusters(team), start, end, today=today)
	rated = rate_team_period(team, start, end, metered=metered)

	invoice = _invoice(rated)
	return {
		"team": team,
		"period_start": str(start),
		"period_end": str(end),
		"as_of": str(today),
		"currency": frappe.db.get_value("Billing Profile", team, "currency"),
		"invoice": invoice,
		"calendar": _calendar(end, today),
		"in_flight": _in_flight(team, today),
	}


def _invoice(rated) -> dict | None:
	"""The projected invoice, with its lines' provenance carried into the totals."""
	if not rated:
		return None

	# Fixed lines come off the real line engine as facts: the rate is locked and the
	# days are arithmetic. Only metering had to be inferred, and it labelled itself.
	lines = mark(rated.payload["items"], MEASURED)
	totals = split_totals(lines)
	payload = rated.payload
	return {
		"lines": lines,
		"subtotal": payload["subtotal"],
		"commitment_discount": payload["commitment_discount"],
		"commitment_clawback": payload["commitment_clawback"],
		"output_tax_type": payload["output_tax_type"],
		"output_tax_rate": payload["output_tax_rate"],
		"output_tax_amount": payload["output_tax_amount"],
		"tds_amount": payload["tds_amount"],
		"total": payload["total"],
		"expected_collection": payload["expected_collection"],
		"invoice_type": payload["invoice_type"],
		# Never a bare total: a bill that is part guesswork must not read like a bill.
		"measured": totals["measured"],
		"estimated": totals["estimated"],
		"has_estimates": totals["has_estimates"],
	}


def _opens_on(period_end):
	"""The day the run would open this period's invoice.

	Drafting fires on the 1st after the period closes, because a month billed in
	arrears is not closed until it ends.
	"""
	return frappe.utils.add_days(frappe.utils.getdate(period_end), 1)


def _calendar(period_end, today) -> dict:
	"""Both branches of what happens next, dated.

	The fork is the point of the thing: an operator asking "what happens to this team"
	wants to see settlement *and* escalation side by side, not one of them behind a
	mode switch. Neither branch is asserted here — deriving which one the team's state
	entails is a later, separate job.
	"""
	opens_on = _opens_on(period_end)
	due_on = frappe.utils.add_days(opens_on, settings.invoice_due_days())
	return {
		"opens_on": str(opens_on),
		"due_on": str(due_on),
		"if_paid_on_time": [{"date": str(due_on), "stage": "Settled"}],
		"if_never_paid": _ladder(due_on),
	}


def _ladder(clock_start, policy=None) -> list[dict]:
	"""The escalation ladder as plain dated rows."""
	return [
		{
			"date": str(s.date),
			"stage": s.stage,
			"day": s.day,
			**({"attempt": s.attempt} if s.get("attempt") else {}),
		}
		for s in dunning_schedule(clock_start, policy or dunning_policy())
	]


def _in_flight(team: str, today) -> list[dict]:
	"""Invoices already unpaid, and where their ladders have got to.

	A projection that only laddered the invoice it just priced would miss the urgent
	case entirely — a team mid-escalation on last month's bill. These carry their real
	`dunning_starts_on`, so a clock we deferred because *our* collection failed is
	honoured rather than counted against the customer.
	"""
	unpaid = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["in", ["Open", "Overdue"]],
			"expected_collection": [">", 0],
		},
		fields=["name", "status", "due_date", "dunning_starts_on", "expected_collection", "currency"],
		order_by="due_date asc",
	)

	out = []
	for inv in unpaid:
		if not inv.due_date:
			continue
		clock_start = dunning_clock_start(inv)
		out.append(
			{
				"invoice": inv.name,
				"status": inv.status,
				"currency": inv.currency,
				"outstanding": inv.expected_collection,
				"due_date": str(inv.due_date),
				"clock_starts_on": str(clock_start),
				"clock_deferred": bool(inv.dunning_starts_on),
				"ladder": _ladder(clock_start),
				"days_in": (today - frappe.utils.getdate(clock_start)).days,
			}
		)
	return out
