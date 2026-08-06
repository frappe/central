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
from central.billing.projection import estimate, outcomes, state
from central.billing.projection.basis import MEASURED, mark, split_totals
from central.billing.projection.guard import read_only
from central.billing.revenue.dunning import dunning_clock_start, dunning_policy, dunning_schedule
from central.billing.revenue.invoicing.generate import rate_team_period, team_clusters


def project(
	team: str,
	period_start,
	period_end,
	today=None,
	mode: str = outcomes.DERIVED,
	assume: str | None = None,
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
		return _project(team, period_start, period_end, today, mode, assume)


def _project(
	team: str, period_start, period_end, today=None, mode: str = outcomes.DERIVED, assume=None
) -> dict:
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	start = frappe.utils.getdate(period_start)
	end = frappe.utils.getdate(period_end)

	metered = estimate.metered_lines(team, team_clusters(team), start, end, today=today)
	rated = rate_team_period(team, start, end, metered=metered)

	invoice = _invoice(rated)
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	calendar = _calendar(end, today)

	# Derived findings are read off the amount we would actually try to collect, not the
	# headline total: credits and withholding both change what the gateway is asked for.
	collectable = invoice["expected_collection"] if invoice else 0.0
	findings = (
		outcomes.derive(team, collectable, currency, calendar["due_on"], today)
		if mode == outcomes.DERIVED
		else []
	)

	return {
		"team": team,
		"period_start": str(start),
		"period_end": str(end),
		"as_of": str(today),
		"currency": currency,
		"invoice": invoice,
		"calendar": calendar,
		"outcome": outcomes.verdict(mode, findings, assume),
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
	mode switch. Neither branch is asserted here — `outcomes.verdict` marks which arm
	the team's state entails, if either, and both are rendered regardless.
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


def project_months(
	team: str,
	start,
	months: int = 1,
	today=None,
	mode: str = outcomes.DERIVED,
	assume: str | None = None,
) -> dict:
	"""Roll a team forward month by month, carrying what each month changes.

	This is the question a single-period projection cannot answer: not "what is the
	September bill" but "when does this team run out". Each month is priced, settled
	against the wallet the previous months left behind, escalated if it goes unpaid,
	and the consequences carried into the next — which is how a projection arrives at
	"credits run dry in month three, suspended in month four" rather than reporting a
	comfortable balance every month because it re-read today's.
	"""
	with read_only():
		return _project_months(team, start, months, today, mode, assume)


def _project_months(team, start, months, today=None, mode=outcomes.DERIVED, assume=None) -> dict:
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	carried = state.seed(team, today)
	period_start = frappe.utils.get_first_day(start)

	periods = []
	for _ in range(max(1, frappe.utils.cint(months))):
		period_end = frappe.utils.get_last_day(period_start)
		periods.append(_roll_one(team, carried, period_start, period_end, today, mode, assume))
		period_start = frappe.utils.add_days(period_end, 1)

	return {
		"team": team,
		"as_of": str(today),
		"currency": carried.currency,
		"months": periods,
		"ends": {
			"balance": carried.wallet().balance,
			"standing": carried.standing,
			"suspended_on": str(carried.suspended_on) if carried.suspended_on else None,
			"tier_cap": carried.tier_cap(team),
		},
		"events": carried.events,
	}


def _roll_one(team, carried, period_start, period_end, today, mode, assume) -> dict:
	"""One month, against the state the months before it left behind."""
	# Promotional credit dies on its date whether or not anyone spent it. Sweep at the
	# start of the month, not the end: a grant expiring on the 30th is the customer's to
	# spend right up to the 30th, and destroying it before the month it covers would
	# under-credit them by a whole period.
	carried.expire_credits(frappe.utils.add_days(period_start, -1))

	# A suspended resource is stopped, and a stopped resource is not billed on. The
	# accrual ends at the suspension, not at the end of the projection.
	if carried.suspended:
		return {
			"period_start": str(period_start),
			"period_end": str(period_end),
			"suspended": True,
			"invoice": None,
			"settlement": None,
			"calendar": None,
			"outcome": None,
		}

	metered = estimate.metered_lines(team, team_clusters(team), period_start, period_end, today=today)
	rated = rate_team_period(team, period_start, period_end, metered=metered)
	invoice = _invoice(rated)
	calendar = _calendar(period_end, today)

	settlement_result = _settle(carried, invoice, calendar, mode, assume)
	findings = (
		outcomes.derive(team, settlement_result["shortfall"], carried.currency, calendar["due_on"], today)
		if mode == outcomes.DERIVED and invoice
		else []
	)
	verdict = outcomes.verdict(mode, findings, assume)

	# Nothing recovered means the ladder runs, and the ladder ends in suspension.
	if invoice and settlement_result["shortfall"] > 0 and verdict.entailed_branch == "if_never_paid":
		suspend = next((s for s in calendar["if_never_paid"] if s["stage"] == "Suspend"), None)
		if suspend:
			carried.suspend(suspend["date"])

	return {
		"period_start": str(period_start),
		"period_end": str(period_end),
		"suspended": False,
		"invoice": invoice,
		"settlement": settlement_result,
		"calendar": calendar,
		"outcome": verdict,
		"balance_after": carried.wallet().balance,
		"standing": carried.standing,
	}


def _settle(carried, invoice, calendar, mode, assume) -> dict | None:
	"""Draw the projected wallet down, then say what is left owing.

	Credits first, then whatever a card would have to cover — the same waterfall the
	real settlement follows. Only what credits actually cover is certain here; the card
	leg is exactly the part a projection must not claim to know.
	"""
	if not invoice:
		return None

	owed = frappe.utils.flt(invoice["expected_collection"])
	drawn = carried.settle(owed)
	shortfall = frappe.utils.flt(owed - drawn, 2)

	# An invoice the operator says is paid, or one credits covered outright, is money
	# in — and settled invoices are what move a team up the trust ladder.
	settled = shortfall <= 0 or (mode == outcomes.ASSUMED and assume == "pays_on_time")
	if settled:
		carried.record_paid(invoice["total"])

	return {
		"owed": owed,
		"from_credits": drawn,
		"shortfall": max(0.0, shortfall),
		"settled_by_credits": shortfall <= 0,
	}
