# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the ₹15,000 "Action Required" threshold (issue #50, ADR 0005).

Billing is usage-based and variable. In India an *off-session* recurring debit
above ₹15,000 needs the customer to re-authenticate every cycle (an RBI rule), so
we auto-charge silently only while the bill stays under that line. The moment an
e-mandate team's bill (or its month-to-date forecast) crosses ₹15,000 we stop
trying to charge silently and flip the team to `action_required` — the account
keeps running until the customer picks `manual_checkout` (pay each invoice
on-session, any amount) or `prepaid` (fund the wallet).

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


def gateway_ceiling(team: str) -> float | None:
	"""The regulatory ceiling on the rail this team's bill would be pulled through,
	in major units; None where the currency carries no ceiling (ADR 0022).

	Which rail that is follows the team's own primary method, because gateway is a
	property of the method rather than of the charge. A team with no method yet is
	measured against the default gateway for its currency, which is the rail it
	would land on if it added one now.

	A team with no rail at all is held to whatever the law imposes on its currency.
	The ₹15,000 line an Indian team lives under does not disappear because it has
	not added a payment method yet.
	"""
	currency = frappe.db.get_value("Billing Profile", team, "currency")
	if not currency:
		return None

	gateway = frappe.db.get_value(
		"Payment Method",
		{"team": team, "status": "Active", "reauth_required": 0},
		"gateway",
		order_by="priority asc, creation asc",
	) or _default_gateway(currency)
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
	"""Re-check an `emandate` team against the silent-debit threshold and trip
	`action_required` if `projected_amount` (₹, major units) crosses it. A no-op for
	any other mode (so it's safe to call from the charge loop / dashboard). Returns
	the current status()."""
	mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	if mode == "E-Mandate" and projected_amount is not None:
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
	"""Customer resolves action_required (or switches) to manual_checkout / prepaid.
	Reversible and idempotent; clears the action reason."""
	if mode not in CUSTOMER_CHOOSABLE:
		frappe.throw(_("Pick one of {0}.").format(", ".join(CUSTOMER_CHOOSABLE)), frappe.ValidationError)
	profile = frappe.get_doc("Billing Profile", team)
	profile.collection_mode = mode
	profile.collection_action_reason = None
	profile.save(ignore_permissions=True)
	return status(team)


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
	}
