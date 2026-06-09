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
"""

import frappe

from central.billing.revenue import credits

AUTOPAY_METHODS = ("card", "upi_autopay")
FORECAST_NOTIFY_RATIO = 0.8


def settlement_sources(team: str) -> dict:
	"""What the team can settle with: active autopay method and/or wallet credit."""
	has_autopay = bool(
		frappe.get_all(
			"Payment Method",
			filters={"team": team, "method_type": ["in", AUTOPAY_METHODS], "status": "active"},
			limit=1,
		)
	)
	has_credits = credits.get_balance(team)["balance"] > 0
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
			"A team needs at least one settlement source (autopay or prepaid credits) "
			"before it can provision.",
			frappe.ValidationError,
		)


def _tier_cap(team: str):
	return frappe.utils.flt(frappe.db.get_value("Trust Tier", team, "max_spend"))


def effective_spend_cap(team: str):
	"""The cap the team is actually held to.

	Autopay teams follow the trust tier directly (the card is the backstop).
	Credits-only teams are gated by the wallet: `min(tier cap, balance)` — a cap
	enforced without a backstop would be unsecured in a postpaid system.
	"""
	tier_cap = _tier_cap(team)
	sources = settlement_sources(team)
	if sources["credits_only"]:
		return min(tier_cap, frappe.utils.flt(credits.get_balance(team)["balance"]))
	return tier_cap


def can_accept_spend(team: str, projected_spend) -> bool:
	"""Whether a new provision's projected run-rate fits the effective cap.

	For credits-only teams this denies provisioning beyond wallet coverage; for
	autopay teams it is the plain tier check.
	"""
	return frappe.utils.flt(projected_spend) <= effective_spend_cap(team)


def credit_forecast(team: str, projected_spend, notify: bool = True) -> dict:
	"""Compare projected month-end spend to the wallet balance.

	Returns the utilisation and whether a top-up prompt is due (projected spend
	has reached ~80% of the balance). Fires the prompt as a side effect when
	`notify` and the threshold is crossed; the #20 suite is the real sender.
	"""
	balance = frappe.utils.flt(credits.get_balance(team)["balance"])
	projected = frappe.utils.flt(projected_spend)
	utilisation = (projected / balance) if balance > 0 else (1.0 if projected > 0 else 0.0)
	should_notify = utilisation >= FORECAST_NOTIFY_RATIO

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

	notifications.notify(team, "credit_low", context={"utilisation": f"{utilisation:.0%}"})
	frappe.publish_realtime(
		"billing_top_up_prompt",
		{"team": team, "balance": balance, "projected_spend": projected, "utilisation": utilisation},
	)
