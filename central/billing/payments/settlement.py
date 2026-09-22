# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Settlement sources + credits-only wallet gating (issue #11).

Every team needs at least one settlement source — card/mandate autopay or
prepaid credits (or both). When both exist the bill is drawn credits-first,
then card (the waterfall in billing.open_and_collect).

A **credits-only** team (no autopay) is unsecured in a postpaid system, so the
wallet gates provisioning: its effective spend cap is `min(tier cap, wallet
balance)`. The running forecast compares projected month-end spend to the
balance and, at ~80%, prompts a top-up; the next token refresh shrinks the cap
*before* an overspend. Running resources are never stopped for this — only the
residual shortfall at settlement flows into dunning.

The same wallet rule lets a new team provision on credits before it has given us
its billing details; those are asked for once the credits stop covering the bill.
"""

import frappe
from frappe import _

from central.billing import settings
from central.billing.revenue import credits

AUTOPAY_METHODS = ("Card", "UPI Autopay")

BILLING_DETAILS_ASK = "Billing Details Required"

# How often one team is reminded. Daily would be a daily email to every member.
REMINDER_EVERY_DAYS = 7

# Per-team undo point for the reminder sweep, so one team's failure costs only its own ask.
_REMINDER_SAVEPOINT = "billing_details_reminder"


def settlement_sources(team: str, source=None) -> dict:
	"""What the team can settle with: active autopay method and/or wallet credit.

	`source` defers the evolving parts — the wallet, and whether a method is still
	active — to a projection's roll-forward state. Absent, everything is read live.
	"""
	if source is not None:
		has_autopay = bool(source.has_autopay(team))
	else:
		has_autopay = bool(
			frappe.get_all(
				"Payment Method",
				filters={"team": team, "method_type": ["in", AUTOPAY_METHODS], "status": "Active"},
				limit=1,
			)
		)
	has_credits = credits.get_balance(team, source=source)["balance"] > 0
	return {
		"has_autopay": has_autopay,
		"has_credits": has_credits,
		"has_any": has_autopay or has_credits,
		"credits_only": has_credits and not has_autopay,
	}


def ensure_settlement_source(team: str):
	"""Onboarding gate: refuse a team with no way to pay (card/mandate or credits)."""
	if not settlement_sources(team)["has_any"]:
		frappe.throw(
			_(
				"A team needs at least one settlement source (autopay or prepaid credits) "
				"before it can provision."
			),
			frappe.ValidationError,
		)


def _tier_cap(team: str, source=None):
	if source is not None:
		return frappe.utils.flt(source.tier_cap(team))

	from central.billing.catalog.entitlements import get_team_caps

	return frappe.utils.flt(get_team_caps(team).max_spend)


def effective_spend_cap(team: str, source=None):
	"""The cap the team is actually held to.

	Autopay teams follow the trust tier directly (the card is the backstop).
	Credits-only teams are gated by the wallet: `min(tier cap, balance)` — a cap
	enforced without a backstop would be unsecured in a postpaid system.
	"""
	tier_cap = _tier_cap(team, source)
	sources = settlement_sources(team, source)
	if sources["credits_only"]:
		return min(tier_cap, frappe.utils.flt(credits.get_balance(team, source=source)["balance"]))
	return tier_cap


def can_accept_spend(team: str, projected_spend, source=None) -> bool:
	"""Whether a new provision's projected run-rate fits the effective cap.

	For credits-only teams this denies provisioning beyond wallet coverage; for
	autopay teams it is the plain tier check.
	"""
	return frappe.utils.flt(projected_spend) <= effective_spend_cap(team, source)


def credit_funded_headroom(team: str, for_update: bool = False) -> float:
	"""How much *more* monthly run-rate the team's own credits can fund.

	Wallet balance under the tier ceiling, less what the team already runs. Always
	wallet-bound: no credits means no headroom, not the bare tier cap. Nothing is
	funded once a bill has waited out the grace period for the team's details.

	`for_update` is for the caller that will act on the answer: it takes the team's
	wallet lock and reads the run rate through it. Without it two creates read the
	same numbers at once and both provision. The dashboard asks without the lock —
	there it is a figure on a card, not a decision.
	"""
	from central.billing.catalog.subscriptions import locked_team_run_rate, team_run_rate

	if details_overdue(team):
		return 0.0
	if for_update:
		# Wallet first, then the subscriptions: one order everywhere, so a booking
		# and a provision can never hold each other's next lock.
		balance = credits.lock_team_wallet(team)
		running = locked_team_run_rate(team)
	else:
		balance = frappe.utils.flt(credits.get_balance(team)["balance"])
		running = team_run_rate(team)
	return max(0.0, min(_tier_cap(team), balance) - running)


def details_overdue(team: str) -> bool:
	"""Whether a bill has waited longer than the grace period for this team's details.

	Credit is extended on the promise of an invoice we can issue. Past the grace
	period that promise has not been kept, so the team funds nothing new until it
	is — what is already running is left alone.
	"""
	from central.billing.api.dashboard._shared import _missing_profile_fields
	from central.billing.revenue.invoicing.lifecycle import held_drafts

	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -settings.billing_details_grace_days())
	if not held_drafts(team, held_before=cutoff, limit=1):
		return False
	return bool(_missing_profile_fields(team))


def wallet_funds(team: str, new_rate) -> bool:
	"""Whether credits cover `new_rate` of extra monthly run-rate. None is never funded.

	The answer is held: the team's wallet stays locked until the caller's request
	commits, so the create it clears is counted before the next one is judged.
	"""
	if new_rate is None:
		return False
	return frappe.utils.flt(new_rate) <= credit_funded_headroom(team, for_update=True)


def credit_forecast(team: str, projected_spend, notify: bool = True, source=None) -> dict:
	"""Compare projected month-end spend to the wallet balance.

	Returns the utilisation and whether a top-up prompt is due (projected spend
	has reached ~80% of the balance). Fires the prompt as a side effect when
	`notify` and the threshold is crossed; the #20 suite is the real sender.
	"""
	balance = frappe.utils.flt(credits.get_balance(team, source=source)["balance"])
	projected = frappe.utils.flt(projected_spend)
	utilisation = (projected / balance) if balance > 0 else (1.0 if projected > 0 else 0.0)
	should_notify = utilisation >= settings.forecast_notify_ratio()

	if notify and should_notify:
		_notify_top_up(team, balance, projected, utilisation)

	return {
		"balance": balance,
		"projected_spend": projected,
		"utilisation": utilisation,
		"notify": should_notify,
		"shortfall": max(0.0, projected - balance),
	}


def _notify_top_up(team: str, balance, projected, utilisation):
	"""Emit the credit-low top-up prompt through the notification suite (#20)."""
	from central.billing.platform import notifications

	notifications.notify(team, "Credit Low", context={"utilisation": f"{utilisation:.0%}"})
	frappe.publish_realtime(
		"billing_top_up_prompt",
		{"team": team, "balance": balance, "projected_spend": projected, "utilisation": utilisation},
	)


def run_billing_details_reminder() -> int:
	"""Daily: ask every team that is running something but has no details on file.

	Fans the teams out in bounded pages, one job each, the way the billing run does:
	a page is the unit a worker owns and the transaction it commits, so the sweep
	needs no commit of its own. Returns how many pages were queued.
	"""
	from central.billing.revenue.invoicing.run import active_team_pages, billing_queue

	pages = 0
	for page in active_team_pages():
		frappe.enqueue(
			"central.billing.payments.settlement.remind_team_page",
			queue=billing_queue(),
			job_id=f"billing-details-ask::{page[-1]}",
			deduplicate=True,
			teams=page,
		)
		pages += 1
	return pages


def remind_team_page(teams: list[str]) -> int:
	"""Ask one page of teams for the billing details their invoice will need.

	A team is asked at most once a week: the notification engine only suppresses a
	repeat for an hour, which for a standing ask is a daily nag and a daily email to
	every member. Returns how many teams were asked.
	"""
	missing = _teams_missing_details(teams)
	for team in _asked_recently(list(missing)):
		missing.pop(team, None)
	return sum(_ask_for_details(team, fields) for team, fields in missing.items())


def _asked_recently(teams: list[str]) -> set[str]:
	"""Which of these teams we have already asked inside the reminder window — read
	in one query for the whole page."""
	if not teams:
		return set()
	since = frappe.utils.add_days(frappe.utils.now_datetime(), -REMINDER_EVERY_DAYS)
	return set(
		frappe.get_all(
			"Billing Notification Log",
			filters={
				"team": ["in", teams],
				"event_type": BILLING_DETAILS_ASK,
				"creation": [">=", since],
			},
			pluck="team",
			distinct=True,
		)
	)


def _ask_for_details(team: str, missing: list[str]) -> int:
	"""Ask one team, returning 1 if we did.

	One team we cannot reach is not the end of the sweep: its half-written ask is
	rolled back to the savepoint so the rest of the page still commits.
	"""
	from central.billing.platform import notifications

	frappe.db.savepoint(_REMINDER_SAVEPOINT)
	try:
		notifications.notify(team, BILLING_DETAILS_ASK, message=", ".join(missing))
		return 1
	except Exception:
		frappe.db.rollback(save_point=_REMINDER_SAVEPOINT)
		frappe.log_error(title=f"Billing details reminder failed: {team}", message=frappe.get_traceback())
		return 0


def _teams_missing_details(teams: list[str]) -> dict[str, list[str]]:
	"""Which of these teams still owe us billing details, and which ones."""
	from central.billing.api.dashboard._shared import (
		_REQUIRED_PROFILE_FIELDS,
		missing_profile_fields_in,
		profile_field_labels,
	)

	profiles = {
		row.team: row
		for row in frappe.get_all(
			"Billing Profile",
			filters={"team": ["in", teams]},
			fields=["team", *_REQUIRED_PROFILE_FIELDS],
		)
	}
	missing = {team: missing_profile_fields_in(profiles.get(team)) for team in teams}
	return {team: profile_field_labels(fields) for team, fields in missing.items() if fields}
