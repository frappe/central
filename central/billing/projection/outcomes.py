# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Why collection will fail — asserted only where the team's state entails it.

Whether a card will succeed is unknowable, so a projection never pretends. But a
great deal of failure is not a guess at all: a team with no active payment method
will not be auto-charged, an INR bill over the silent-debit threshold lands in Action
Required by design, a mandate whose ceiling sits below the invoice cannot be debited.
Those are facts already in the database, and reporting only those is what turns the
simulator from a picture into a pre-flight check on the book.

Three modes, and the output always says which produced it:

  Optimistic  everything settles on time.
  Assumed     the operator declares the outcome; the calendar follows their word.
  Derived     failure is reported only where state entails it, silence otherwise.

Every rule below reuses the production helper that governs it — `silent_threshold`,
`effective_cap`, `settlement_sources`, `ordered_methods` — so the simulator and the
collector cannot disagree about who can be charged.

One helper is deliberately *not* used. `collection_mode.evaluate()` decides the same
threshold question but **trips the profile into Action Required as a side effect**,
which is a write. A projection asks; it does not push the team into a new mode.
"""

import frappe

from central.billing.payments import collection, collection_mode, mandates, settlement

OPTIMISTIC = "Optimistic"
ASSUMED = "Assumed"
DERIVED = "Derived"
MODES = (OPTIMISTIC, ASSUMED, DERIVED)

# Modes in which nothing is charged off-session: the customer has to act. Dunning
# knows this and escalates without retrying (ADR 0005).
ON_SESSION_MODES = ("Manual Checkout", "Action Required")


def derive(team: str, amount: float, currency: str, due_on, today) -> list[frappe._dict]:
	"""Everything about this team's state that already decides the outcome.

	Returns findings, worst first. An empty list is not a prediction of success — it
	means nothing in the data settles the question, and the honest answer is that the
	charge may or may not go through.
	"""
	amount = frappe.utils.flt(amount)
	profile_mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	sources = settlement.settlement_sources(team)
	findings = []

	if profile_mode in ON_SESSION_MODES:
		findings.append(
			_finding(
				"on_session_mode",
				f"Collection mode is {profile_mode}",
				"Nothing is charged off-session in this mode — the customer has to act, "
				"and dunning escalates without retrying.",
			)
		)

	# An e-mandate bill at or over the silent-debit ceiling is never quietly taken; the
	# real charge path trips the team into Action Required at exactly this point.
	if profile_mode == "E-Mandate" and amount:
		threshold = collection_mode.silent_threshold(team)
		if amount >= threshold:
			findings.append(
				_finding(
					"over_silent_threshold",
					"Over the silent-debit threshold",
					f"{_money(amount, currency)} is at or above {_money(threshold, currency)}, "
					"so this lands in Action Required rather than being auto-charged.",
				)
			)

	methods = collection.ordered_methods(team)
	if not methods and not sources["has_credits"]:
		findings.append(
			_finding(
				"no_settlement_source",
				"No way to pay",
				"No active payment method and no credit balance, so there is nothing to "
				"charge and nothing to draw down.",
			)
		)
	elif not methods:
		findings.append(
			_finding(
				"no_active_method",
				"No active payment method",
				"Nothing to auto-charge. Anything credits cannot cover will go unpaid.",
			)
		)

	if mandates.reauth_pending(team):
		findings.append(
			_finding(
				"mandate_reauth_pending",
				"A mandate is awaiting re-authorisation",
				"Until the customer re-consents its ceiling stays where it was, and the "
				"method is skipped by the charge loop.",
			)
		)

	# The mandate ceiling is the amount the bank will actually let us take — but only
	# where a mandate exists. `effective_cap` falls back to the trust-tier cap when
	# there is none, and reporting that as "over the mandate cap" is wrong twice over:
	# there is no mandate, and an unset tier reads as a ceiling of zero, which would
	# flag every team that has not been tiered yet.
	ceiling = mandates.active_mandate_ceiling(team)
	cap = mandates.effective_cap(team)
	if amount and ceiling is not None and frappe.utils.flt(cap) < amount:
		findings.append(
			_finding(
				"over_mandate_cap",
				"Over the mandate cap",
				f"{_money(amount, currency)} exceeds the effective cap of "
				f"{_money(cap, currency)}, so the debit would be refused.",
			)
		)

	if sources["credits_only"] and amount:
		balance = frappe.utils.flt(settlement.credits.get_balance(team, currency)["balance"])
		if balance < amount:
			findings.append(
				_finding(
					"credits_shortfall",
					"Credits will not cover it",
					f"{_money(balance, currency)} against {_money(amount, currency)} — "
					f"short by {_money(amount - balance, currency)}, with no card behind it.",
				)
			)

	findings += _expiring_cards(team, due_on)
	return findings


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
					f"{card.display_label or card.name} expires {expires}, before the "
					f"{due} charge.",
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
