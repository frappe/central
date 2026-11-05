# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What we will charge next, and whether it will work.

The engine already answers the second half: `projection.outcomes.derive` reports
failure only where the team's own state entails it — no active method, a bill over
the silent-debit ceiling, a mandate whose cap sits below the invoice. It reuses the
production helpers the collector runs on, so the two cannot disagree about who can
be charged.

What it does not do is speak to a customer. Its findings are written for an operator
reading a book of teams ("the customer has to act", "lands in Action Required"), so
this module keeps the reasoning and replaces the prose: one entry per finding code,
saying what happened and what to do about it. An unmapped code falls back to the
finding's own summary, which is a short neutral phrase rather than operator detail.
"""

import frappe
from frappe import _

from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.doctype.billing_profile.billing_profile import get_payment_date
from central.billing.doctype.invoice.invoice import owed_filters

# Customer-facing copy for the findings the engine can raise. `fix` is the sentence
# that tells someone what to actually do — the reason this is worth showing at all.
_BLOCKER_COPY = {
	"over_mandate_cap": {
		"title": "We can't auto-debit this",
		"fix": "Add credit to cover it, or pay this bill manually. Your servers keep running either way.",
	},
	"over_silent_threshold": {
		"title": "This bill needs your approval",
		"fix": "Bills above the auto-debit limit have to be paid by you. We'll send a link when it's due.",
	},
	"no_settlement_source": {
		"title": "No way to pay this",
		"fix": "Add a payment method or top up your wallet before the due date.",
	},
	"no_active_method": {
		"title": "No active payment method",
		"fix": "Add one, or make sure your wallet covers the bill.",
	},
	"mandate_reauth_pending": {
		"title": "Your auto-pay needs re-approving",
		"fix": "Re-authorise the mandate so we can keep collecting automatically.",
	},
	"credits_shortfall": {
		"title": "Your credits won't cover this",
		"fix": "Top up the difference, or add a payment method to cover the rest.",
	},
	"on_session_mode": {
		"title": "You pay these bills manually",
		"fix": "We'll notify you when the bill is ready. Switch to auto-pay any time.",
	},
	"card_expiring": {
		"title": "Your card expires before this is due",
		"fix": "Update the card so the payment isn't refused.",
	},
}


@frappe.whitelist()
def get_next_payment(team: str | None = None) -> dict:
	"""The next debit: when, how much, from which instrument — and what would stop it.

	Reads the collectable amount off an already-open invoice where one exists, and
	falls back to the current month's projection when the period is still running.
	`charge_on` is always the next scheduled payment day: the earliest upcoming charge
	of an owed invoice, else the running cycle's. When the oldest owed invoice's own
	payment date has passed, its place on the dunning ladder is reported beside it.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	today = frappe.utils.getdate()

	owed = _owed_invoices(team)
	invoice = owed[0] if owed else None
	if invoice:
		amount = frappe.utils.flt(invoice.expected_collection)
		period_end = invoice.period_end
	else:
		amount, period_end = _projected_collectable(team, today)

	charge_on = _scheduled_charge_on(team, owed, today)
	missed = _missed_payment(team, invoice, today)
	blockers = _blockers(team, amount, currency, missed["next_retry_on"] or charge_on, today)
	return {
		"currency": currency,
		"amount": amount,
		"charge_on": str(charge_on) if charge_on else None,
		"invoice": invoice.name if invoice else None,
		"period_end": str(period_end) if period_end else None,
		"collection_mode": frappe.db.get_value("Billing Profile", team, "collection_mode"),
		"method": _charging_method(team),
		# Empty blockers is not a promise the charge succeeds — only that nothing in
		# the data decides otherwise. The UI says "we'll charge", never "it will work".
		"will_auto_charge": not blockers,
		"blockers": blockers,
		**missed,
	}


@frappe.whitelist()
def get_payment_schedule(team: str | None = None) -> dict:
	"""The tray behind the next-payment card: the debit, the notices we sent, and
	what happens if it goes unpaid."""
	team = _resolve_team(team)
	next_payment = get_next_payment(team)
	period_end = next_payment["period_end"]
	return {
		**next_payment,
		"notices": _predebit_notices(team),
		"if_unpaid": _escalation(team, next_payment["invoice"], period_end),
	}


def _owed_invoices(team: str) -> list[frappe._dict]:
	"""The open bills we still have to collect, oldest due first."""
	return frappe.get_all(
		"Invoice",
		filters=[
			*owed_filters(),
			["team", "=", team],
			["invoice_type", "=", "Billable"],
			["expected_collection", ">", 0],
		],
		fields=[
			"name",
			"status",
			"expected_collection",
			"due_date",
			"dunning_starts_on",
			"suspends_on",
			"payment_date",
			"period_end",
			"predebit_charge_after",
		],
		order_by="due_date asc",
	)


def _invoice_charge_on(invoice):
	"""When the open invoice is charged: its pre-debit charge time, else its payment date."""
	return invoice.predebit_charge_after or invoice.payment_date


def _is_charge_missed(invoice, today) -> bool:
	"""The open invoice's charge day has passed without the bill being settled."""
	charge_on = _invoice_charge_on(invoice)
	return bool(charge_on) and frappe.utils.getdate(charge_on) < today


def _scheduled_charge_on(team: str, owed: list, today):
	"""The next scheduled payment day: the earliest charge day, today or later, among the
	owed invoices, else the day the running cycle's invoice is charged."""
	upcoming = [
		_invoice_charge_on(invoice)
		for invoice in owed
		if _invoice_charge_on(invoice) and not _is_charge_missed(invoice, today)
	]
	if upcoming:
		return min(upcoming, key=frappe.utils.getdate)
	return get_payment_date(team, frappe.utils.add_days(frappe.utils.get_last_day(today), 1))


def _missed_payment(team: str, invoice, today) -> dict:
	"""Where a missed bill stands on the dunning ladder.

	1. No missed bill: all three dates are empty.
	2. A suspended team: only the date it was suspended.
	3. A retry still to come, today's included until it runs: only the next retry date.
	4. No retry left, or none dunning can run: only the date the team is suspended.
	"""
	from central.billing.revenue.dunning import dunning_schedule, get_ladder_dates

	missed = {"next_retry_on": None, "suspends_on": None, "suspended_since": None}
	if not invoice or not _is_charge_missed(invoice, today):
		return missed

	suspended_since = _suspended_since(team)
	if suspended_since:
		return {**missed, "suspended_since": str(frappe.utils.getdate(suspended_since))}

	schedule = dunning_schedule(get_ladder_dates(invoice))
	next_retry_on = _next_retry_on(invoice, team, schedule, today)
	if next_retry_on:
		return {**missed, "next_retry_on": str(next_retry_on)}

	suspend_on = next(s.date for s in schedule if s.stage == "Suspend")
	return {**missed, "suspends_on": str(suspend_on)}


def _next_retry_on(invoice, team: str, schedule: list, today):
	"""The first retry still to run, or None when dunning cannot retry the invoice.
	Dunning runs once a day, so a retry dated today stays next until that day's charge
	has been tried."""
	from central.billing.revenue.dunning import has_retry_rail, is_retry_due

	if not has_retry_rail(invoice, team):
		return None
	for stage in schedule:
		if stage.stage != "Retry":
			continue
		retry_on = frappe.utils.getdate(stage.date)
		if retry_on > today or (retry_on == today and is_retry_due(invoice.name, schedule, today)):
			return stage.date
	return None


def _suspended_since(team: str):
	"""When dunning suspended the team, or None while it is not suspended."""
	from central.billing.catalog.subscriptions import anchor_subscription

	anchor = anchor_subscription(team)
	if not anchor or frappe.db.get_value("Subscription", anchor, "account_standing") != "Suspended":
		return None
	return frappe.db.get_value(
		"Subscription Change",
		{"subscription": anchor, "change_type": "Suspended"},
		"effective_at",
		order_by="effective_at desc",
	)


def _projected_collectable(team: str, today) -> tuple[float, object]:
	"""What the current period would collect if it closed as projected."""
	from central.billing.projection import engine

	month_start = frappe.utils.get_first_day(today)
	month_end = frappe.utils.get_last_day(today)
	# Unguarded for the same reason get_forecast is: a customer page must not fail
	# because the request that reached it happened to write something first.
	projection = engine.project(team, month_start, month_end, today=today, guarded=False)
	invoice = projection["invoice"] or {}
	return frappe.utils.flt(invoice.get("expected_collection")), month_end


def _blockers(team: str, amount: float, currency: str, charge_on, today) -> list[dict]:
	"""The engine's findings, said the way a customer would say them."""
	from central.billing.projection import outcomes

	findings = outcomes.derive(team, amount, currency, charge_on, today)
	blockers = []
	for finding in findings:
		copy = _BLOCKER_COPY.get(finding.finding, {})
		blockers.append(
			{
				"code": finding.finding,
				"title": copy.get("title") or finding.summary,
				"fix": copy.get("fix"),
			}
		)
	return blockers


def _charging_method(team: str) -> dict | None:
	"""The instrument that would actually be charged: the primary chargeable one."""
	from central.billing.payments import collection

	methods = collection.ordered_methods(team)
	if not methods:
		return None
	method = frappe.db.get_value(
		"Payment Method",
		methods[0].name,
		["display_label", "method_type", "mandate_max_amount", "card_network"],
		as_dict=True,
	)
	if not method:
		return None
	return {
		"label": method.display_label,
		"method_type": method.method_type,
		"card_network": method.card_network,
		# The ceiling is the number the blocker copy refers to, so it travels with it.
		"ceiling": frappe.utils.flt(method.mandate_max_amount) or None,
	}


def _predebit_notices(team: str, limit: int = 12) -> list[dict]:
	"""The 24-hour notices we queued before debiting an Indian mandate.

	Written on every notice already (ADR 0005); surfacing them is what makes the
	record the customer's rather than only ours.
	"""
	return [
		{
			"queued_at": str(row.queued_at or row.creation),
			"invoice": row.reference_name,
			"subject": row.subject,
			"status": row.status,
		}
		for row in frappe.get_all(
			"Billing Notification Log",
			filters={"team": team, "event_type": "Pre-debit Notice"},
			fields=["reference_name", "subject", "queued_at", "status", "creation"],
			order_by="creation desc",
			limit=limit,
		)
	]


def _escalation(team: str, invoice: str | None, period_end) -> list[dict]:
	"""What happens if the bill goes unpaid — published up front rather than
	discovered one failed retry at a time.

	An open invoice counts from its own ladder dates. A projected one counts from the
	dates the run would give it when it opens."""
	from central.billing.revenue.dunning import (
		dunning_policy,
		dunning_schedule,
		get_ladder_dates,
		get_opening_ladder_dates,
	)

	if invoice:
		dates = get_ladder_dates(
			frappe.db.get_value(
				"Invoice",
				invoice,
				["payment_date", "due_date", "dunning_starts_on", "suspends_on"],
				as_dict=True,
			)
		)
	elif period_end:
		dates = get_opening_ladder_dates(team, frappe.utils.add_days(period_end, 1))
	else:
		return []
	return [
		{"date": str(stage.date), "stage": _(stage.stage), "day": stage.day}
		for stage in dunning_schedule(dates, dunning_policy())
	]
