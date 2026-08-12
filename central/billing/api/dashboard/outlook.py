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
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	today = frappe.utils.getdate()

	invoice = _next_collectable_invoice(team)
	if invoice:
		amount = frappe.utils.flt(invoice.expected_collection)
		charge_on = invoice.predebit_charge_after or invoice.due_date
		period_end = invoice.period_end
	else:
		amount, period_end = _projected_collectable(team, today)
		charge_on = frappe.utils.add_days(period_end, 1)

	blockers = _blockers(team, amount, currency, charge_on, today)
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
		"if_unpaid": _escalation(period_end),
	}


def _next_collectable_invoice(team: str):
	"""The open bill we would collect next, soonest due first."""
	rows = frappe.get_all(
		"Invoice",
		filters={
			"team": team,
			"invoice_type": "Billable",
			"status": ["in", ("Open", "Overdue")],
			"expected_collection": [">", 0],
		},
		fields=["name", "expected_collection", "due_date", "period_end", "predebit_charge_after"],
		order_by="due_date asc",
		limit=1,
	)
	return frappe._dict(rows[0]) if rows else None


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
	"""The 24-hour notices we sent before debiting an Indian mandate.

	Written on every notice already (ADR 0005); surfacing them is what makes the
	record the customer's rather than only ours.
	"""
	return [
		{
			"sent_at": str(row.sent_at or row.creation),
			"invoice": row.reference_name,
			"subject": row.subject,
			"status": row.status,
		}
		for row in frappe.get_all(
			"Billing Notification Log",
			filters={"team": team, "event_type": "Pre-debit Notice"},
			fields=["reference_name", "subject", "sent_at", "status", "creation"],
			order_by="creation desc",
			limit=limit,
		)
	]


def _escalation(period_end) -> list[dict]:
	"""What happens if the bill goes unpaid — published up front rather than
	discovered one failed retry at a time."""
	if not period_end:
		return []
	from central.billing import settings
	from central.billing.revenue.dunning import dunning_policy, dunning_schedule

	opens_on = frappe.utils.add_days(frappe.utils.getdate(period_end), 1)
	due_on = frappe.utils.add_days(opens_on, settings.invoice_due_days())
	return [
		{"date": str(stage.date), "stage": _(stage.stage), "day": stage.day}
		for stage in dunning_schedule(due_on, dunning_policy())
	]
