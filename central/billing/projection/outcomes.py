# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Why collection will fail — asserted only where the team's state entails it.

Whether a card will succeed is unknowable, so a projection never pretends. But a
great deal of failure is not a guess at all: a team with no active payment method
will not be auto-charged, a bill over what every saved method may take off-session
(the INR silent ceiling, or a mandate's maximum) lands in Action Required by design.
Those are facts already in the database, and reporting only those is what turns the
simulator from a picture into a pre-flight check on the book.

Three modes, and the output always says which produced it:

  Optimistic  everything settles on time.
  Assumed     the operator declares the outcome; the calendar follows their word.
  Derived     failure is reported only where state entails it, silence otherwise.

Every check below reuses the production helper that governs it — `off_session_limit`,
`settlement_sources`, `ordered_methods` — so the simulator and the collector cannot
disagree about who can be charged.

A projection asks; it never pushes the team into a new mode (`collection_mode.trip`).
"""

import frappe

from central.billing.payments import collection, collection_mode, mandates, settlement

OPTIMISTIC = "Optimistic"
ASSUMED = "Assumed"
DERIVED = "Derived"
MODES = (OPTIMISTIC, ASSUMED, DERIVED)

# Modes in which nothing is charged off-session: the customer has to act. Dunning
# knows this and escalates without retrying (ADR 0005).
ON_SESSION_MODES = collection_mode.DEBIT_HELD_MODES


def derive(team: str, amount: float, currency: str, due_on, today) -> list[frappe._dict]:
	"""Everything about this team's state that already decides the outcome.

	Returns findings, worst first. An empty list is not a prediction of success — it
	means nothing in the data settles the question, and the honest answer is that the
	charge may or may not go through.
	"""
	amount = frappe.utils.flt(amount)
	sources = settlement.settlement_sources(team)
	return [
		*_on_session_mode(team),
		*_over_silent_threshold(team, amount, currency),
		*_no_way_to_pay(team, sources),
		*_mandate_reauth_pending(team),
		*_credits_shortfall(team, amount, currency, sources),
		*_expiring_cards(team, due_on),
	]


def _on_session_mode(team: str) -> list[frappe._dict]:
	"""A mode in which nothing is charged off-session."""
	profile_mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	if profile_mode not in ON_SESSION_MODES:
		return []
	finding = _finding(
		"on_session_mode",
		f"Collection mode is {profile_mode}",
		"Nothing is charged off-session in this mode — the customer has to act, "
		"and dunning escalates without retrying.",
	)
	return [finding]


def _over_silent_threshold(team: str, amount: float, currency: str) -> list[frappe._dict]:
	"""A bill no saved method may take off-session: over the rail's silent ceiling or
	every mandate's maximum."""
	# The real charge path trips the team into Action Required at exactly this point.
	limit = collection_mode.off_session_limit(team)
	if (
		not amount
		or not collection_mode.is_debit_allowed(team)
		or collection_mode.is_within_limit(limit, amount)
	):
		return []
	finding = _finding(
		"over_silent_threshold",
		"Over the silent-debit threshold",
		f"{_money(amount, currency)} is above {_money(limit, currency)}, "
		"so this lands in Action Required rather than being auto-charged.",
	)
	return [finding]


def _no_way_to_pay(team: str, sources: dict) -> list[frappe._dict]:
	"""No active method, and maybe no credit either."""
	if collection.ordered_methods(team):
		return []
	if sources["has_credits"]:
		finding = _finding(
			"no_active_method",
			"No active payment method",
			"Nothing to auto-charge. Anything credits cannot cover will go unpaid.",
		)
	else:
		finding = _finding(
			"no_settlement_source",
			"No way to pay",
			"No active payment method and no credit balance, so there is nothing to "
			"charge and nothing to draw down.",
		)
	return [finding]


def _mandate_reauth_pending(team: str) -> list[frappe._dict]:
	"""A mandate below the spend limit with GST, until the customer re-consents."""
	if not mandates.reauth_pending(team):
		return []
	finding = _finding(
		"mandate_reauth_pending",
		"A mandate is awaiting re-authorisation",
		"Until the customer re-consents it is charged only up to its old maximum, "
		"so a larger bill goes to the next method.",
	)
	return [finding]


def _credits_shortfall(team: str, amount: float, currency: str, sources: dict) -> list[frappe._dict]:
	"""A credits-only team whose balance will not cover the bill."""
	if not (sources["credits_only"] and amount):
		return []
	balance = frappe.utils.flt(settlement.credits.get_balance(team, currency)["balance"])
	if balance >= amount:
		return []
	finding = _finding(
		"credits_shortfall",
		"Credits will not cover it",
		f"{_money(balance, currency)} against {_money(amount, currency)} — "
		f"short by {_money(amount - balance, currency)}, with no card behind it.",
	)
	return [finding]


def _expiring_cards(team: str, due_on) -> list[frappe._dict]:
	"""Cards whose printed expiry falls before we would charge them."""
	due = frappe.utils.getdate(due_on)
	out = []
	for card in frappe.get_all(
		"Payment Method",
		filters={"team": team, "method_type": "Card", "status": "Active"},
		fields=["name", "display_label", "expiry_month", "expiry_year"],
	):
		if not (card.expiry_month and card.expiry_year):
			continue
		# A card is good through the last day of its printed month.
		expires = frappe.utils.get_last_day(f"{int(card.expiry_year)}-{int(card.expiry_month):02d}-01")
		if frappe.utils.getdate(expires) < due:
			out.append(
				_finding(
					"card_expires",
					"A card expires before it would be charged",
					f"{card.display_label or card.name} expires {expires}, before the {due} charge.",
				)
			)
	return out


def verdict(mode: str, findings: list, assume: str | None = None) -> frappe._dict:
	"""What the projection claims about payment, and on what authority.

	`entailed_branch` is the load-bearing field: it marks which arm of the calendar the
	data already decides, so the UI can show both branches while saying which one is
	not in doubt. None means genuinely open — the charge may work or it may not, and
	nothing here knows which.
	"""
	if mode == OPTIMISTIC:
		return frappe._dict(mode=mode, entailed_branch="if_paid_on_time", findings=[])

	if mode == ASSUMED:
		branch = "if_paid_on_time" if assume == "pays_on_time" else "if_never_paid"
		return frappe._dict(mode=mode, assumed=assume, entailed_branch=branch, findings=[])

	return frappe._dict(
		mode=DERIVED,
		# Any finding at all means the off-session charge does not simply go through.
		entailed_branch="if_never_paid" if findings else None,
		findings=findings,
	)


def _finding(code: str, summary: str, detail: str) -> frappe._dict:
	return frappe._dict(finding=code, summary=summary, detail=detail)


def _money(value, currency: str) -> str:
	"""Format for a human, without asking the database how.

	`fmt_money` resolves the site's number format, and that read can write — which is
	fatal inside the read-only transaction a projection runs in. Presentation does not
	belong in the engine anyway: findings carry plain numbers, and the surface that
	renders them is free to format properly.
	"""
	return f"{currency} {frappe.utils.flt(value):,.2f}"
