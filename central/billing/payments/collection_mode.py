# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the ₹15,000 "Action Required" threshold (ADR 0005, ADR 0022).

Billing is usage-based and variable. In India an *off-session* recurring debit
above ₹15,000 needs the customer to re-authenticate every cycle (an RBI rule that
binds Stripe India and Razorpay alike), so we auto-charge silently only while the
bill stays under that line. The moment an `Auto Charge` team's bill (or its
month-to-date forecast) crosses the ceiling we stop trying to charge silently and
flip the team to `Action Required` — the account keeps running until the customer
picks `Manual Checkout` (pay each invoice on-session, any amount) or `Prepaid`
(fund the wallet).

A mode names what the customer experiences, not which provider we called: an
Indian card mandate on Stripe and a UPI Autopay mandate on Razorpay are both
`Auto Charge`. Whether a ceiling applies is derived from the currency and the
rail's own capability, never from the mode.

This module is the pure state machine over `Billing Profile.collection_mode`; the
forecast number is supplied by the caller (the dashboard computes it in the authed
request, the charge loop passes the invoice total), so the logic stays unit-clean
and side-effect free apart from the profile write + one notification.
"""

import frappe
from frappe import _

from central.billing.gateways import capabilities
from central.billing.payments import mandates

# The modes a customer may pick to resolve action_required (or switch into).
CUSTOMER_CHOOSABLE = ("Manual Checkout", "Prepaid")

# Going back to automatic is also the customer's to make — ADR 0005's hysteresis
# says a quiet month never drags them back on its own, and case 13 says they may
# re-register when eligible. Eligible means there is something to charge: without a
# working method, Auto Charge is a promise nothing can keep.
RETURNABLE = ("Auto Charge",)


def team_rail(team: str) -> tuple[str | None, str | None]:
	"""The (gateway, currency) a team's bill would be pulled through.

	Gateway follows the team's own primary method, because it is a property of the
	method rather than of the charge (ADR 0022). A team with no method yet is read
	against the default gateway for its currency, which is the rail it would land on
	if it added one now.
	"""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if not currency:
		return None, None
	gateway = frappe.db.get_value(
		"Payment Method",
		{"team": team, "status": "Active", "reauth_required": 0},
		"gateway",
		order_by="priority asc, creation asc",
	) or _default_gateway(currency)
	return gateway, currency


def gateway_ceiling(team: str) -> float | None:
	"""The ceiling on the rail this team's bill would be pulled through, in major
	units; None where nothing caps it.

	A team with no rail at all is still held to whatever the law imposes on its
	currency. The ₹15,000 line an Indian team lives under does not disappear because
	it has not added a payment method yet.
	"""
	gateway, currency = team_rail(team)
	if not currency:
		return None
	if not gateway:
		return capabilities.regulatory_ceiling(currency)
	return capabilities.silent_charge_ceiling(gateway, currency)


def _default_gateway(currency: str) -> str | None:
	from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency

	try:
		return resolve_gateway_for_currency(currency)
	except GatewayNotFound:
		return None


def silent_threshold(team: str) -> float | None:
	"""The largest bill we may auto-charge silently: the gateway's ceiling for the
	team's currency and the trust-tier cap, whichever binds first. None means no
	ceiling binds at all, which is not the same as a ceiling of zero.

	In INR the gateway ceiling is ₹15,000 whichever gateway it is, because it is an
	RBI rule rather than a provider limitation. In an unregulated currency the tier
	cap is the whole answer.
	"""
	cap = frappe.utils.flt(mandates.team_cap(team))
	ceiling = gateway_ceiling(team)
	if ceiling is None:
		return float(cap) if cap else None
	return float(min(ceiling, cap)) if cap else float(ceiling)


def evaluate(
	team: str, projected_amount: float | None = None, reason: str = "forecast_over_threshold"
) -> dict:
	"""Re-check an `Auto Charge` team against the silent-debit threshold and trip
	`Action Required` if `projected_amount` (major units) crosses it. A no-op for any
	other mode (so it's safe to call from the charge loop / dashboard). Returns the
	current status()."""
	mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	if mode == "Auto Charge" and projected_amount is not None:
		threshold = silent_threshold(team)
		if threshold is not None and frappe.utils.flt(projected_amount) >= threshold:
			trip(team, reason)
	return status(team)


def trip(team: str, reason: str) -> None:
	"""Pause silent auto-charge and raise Action Required. Idempotent — notifies
	once (a team already in action_required is left as-is)."""
	profile = frappe.get_doc("Billing Profile", team)
	if profile.collection_mode == "Action Required":
		return
	profile.collection_mode = "Action Required"
	profile.collection_action_reason = reason
	profile.save(ignore_permissions=True)

	from central.billing.platform import notifications

	notifications.notify(
		team,
		"Action Required",
		context={"reason": reason, "threshold": silent_threshold(team)},
		reference_doctype="Billing Profile",
		reference_name=team,
	)


def choose(team: str, mode: str) -> dict:
	"""Customer picks how they are collected: Manual Checkout, Prepaid, or back to
	Auto Charge. Reversible and idempotent; clears the action reason.

	Returning to Auto Charge needs a method that can actually be charged. Allowing it
	without one would set a mode whose whole meaning is "we debit something", and the
	first invoice would discover the gap on the customer's behalf.
	"""
	if mode in RETURNABLE:
		if not _has_chargeable_method(team):
			frappe.throw(
				_("Add a card or UPI mandate before switching to automatic payments."),
				frappe.ValidationError,
			)
	elif mode not in CUSTOMER_CHOOSABLE:
		frappe.throw(
			_("Pick one of {0}.").format(", ".join(CUSTOMER_CHOOSABLE + RETURNABLE)),
			frappe.ValidationError,
		)
	profile = frappe.get_doc("Billing Profile", team)
	profile.collection_mode = mode
	profile.collection_action_reason = None
	profile.save(ignore_permissions=True)
	return status(team)


def _has_chargeable_method(team: str) -> bool:
	"""An active method that is not waiting on the customer to re-authorise it."""
	return bool(
		frappe.get_all(
			"Payment Method",
			filters={"team": team, "status": "Active", "reauth_required": 0},
			limit=1,
		)
	)


def status(team: str) -> dict:
	"""The collection state for the Action Required banner / settings surface."""
	p = (
		frappe.db.get_value(
			"Billing Profile", team, ["collection_mode", "collection_action_reason"], as_dict=True
		)
		or frappe._dict()
	)
	mode = p.collection_mode or "Prepaid"
	return {
		"collection_mode": mode,
		"action_required": mode == "Action Required",
		"reason": p.collection_action_reason,
		"threshold": silent_threshold(team),
		"choices": list(CUSTOMER_CHOOSABLE),
		"can_return_to_auto": _has_chargeable_method(team),
	}
