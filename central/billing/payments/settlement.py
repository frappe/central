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


def credit_funded_headroom(team: str) -> float:
	"""How much *more* monthly run-rate the team's own credits can fund.

	Wallet balance under the tier ceiling, less what the team already runs. Always
	wallet-bound: no credits means no headroom, not the bare tier cap.
	"""
	from central.billing.catalog.subscriptions import team_run_rate

	balance = frappe.utils.flt(credits.get_balance(team)["balance"])
	return max(0.0, min(_tier_cap(team), balance) - team_run_rate(team))


def wallet_funds(team: str, new_rate) -> bool:
	"""Whether credits cover `new_rate` of extra monthly run-rate. None is never funded."""
	if new_rate is None:
		return False
	return frappe.utils.flt(new_rate) <= credit_funded_headroom(team)


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
	"""Daily: ask every team that is billable but has no billing details on file.

	The ask is deduped on unread, so it is one standing ask, not a daily nag.
	Returns how many teams were asked.
	"""
	from central.billing.platform import notifications
	from central.billing.revenue.invoicing.run import team_pages

	asked = 0
	for page in team_pages():
		for team, missing in _teams_missing_details(page).items():
			notifications.notify(team, "Billing Details Required", message=", ".join(missing))
			asked += 1
	return asked


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
