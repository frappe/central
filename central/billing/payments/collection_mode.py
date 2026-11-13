# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Collection mode + the off-session limit behind "Action Required".

Billing is usage-based and variable. A saved method may be charged off-session only
up to its limit: the rail's silent ceiling (₹15,000 in INR, an RBI limit that binds
Stripe India and Razorpay alike) or its mandate's maximum, whichever is lower. A
team's off-session limit is the largest of these across its saved methods. A bill
at or under it is charged silently on a method that can take it. When what is left
of an `Auto Charge` or `Prepaid` team's bill after the wallet is over the limit, we
do not try it and flip the team to `Action Required`. A forecast never flips a team:
before the bill, the billing page and a reminder ask for a top-up instead. The account
keeps running until the customer picks `Manual Checkout` (pay each invoice
on-session, any amount) or `Prepaid` (the wallet pays first and the card or UPI
pays only amounts up to the limit, so a larger bill needs enough credit). A
customer who pays an invoice on-session keeps their mode.

A mode names what the customer experiences, not which provider we called: an
Indian card mandate on Stripe and a UPI Autopay mandate on Razorpay are both
`Auto Charge`. Whether a ceiling applies is derived from the currency and the
rail's own capability, never from the mode.

This module is the state machine over `Billing Profile.collection_mode`. The charge
loop decides when a bill trips it; the only side effects are the profile write and one
notification.
"""

import frappe
from frappe import _

from central.billing.gateways import capabilities

# The modes a customer may pick to resolve action_required (or switch into).
CUSTOMER_CHOOSABLE = ("Manual Checkout", "Prepaid")

# Going back to automatic is also the customer's to make — ADR 0005's hysteresis
# says a quiet month never drags them back on its own, and case 13 says they may
# re-register when eligible. Eligible means there is something to charge: without a
# working method, Auto Charge is a promise nothing can keep.
RETURNABLE = ("Auto Charge",)

# The modes that hold an off-session debit back (`is_debit_allowed`).
DEBIT_HELD_MODES = ("Manual Checkout", "Action Required")


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


def _default_gateway(currency: str) -> str | None:
	from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency

	try:
		return resolve_gateway_for_currency(currency)
	except GatewayNotFound:
		return None


def method_limit(gateway: str, currency: str | None, mandate_max_amount: float | None = None) -> float | None:
	"""Most one method may be charged off-session; None when nothing caps it."""
	if not is_off_session_gateway(gateway):
		return 0.0
	if not currency:
		return None
	limits = [
		capabilities.silent_charge_ceiling(gateway, currency),
		frappe.utils.flt(mandate_max_amount) or None,
	]
	limits = [limit for limit in limits if limit is not None]
	return float(min(limits)) if limits else None


def is_off_session_gateway(gateway: str) -> bool:
	"""Whether the gateway can charge a saved method off-session at all."""
	from central.billing.gateways.registry import adapter_class

	adapter_key = frappe.get_cached_value("Payment Gateway", gateway, "adapter_key")
	return bool(adapter_class(adapter_key).supports_off_session_charge)


def off_session_limit(team: str, invoice: str | None = None) -> float | None:
	"""Most the team's saved methods may be charged off-session; None when nothing caps
	it or no method is on file. For an `invoice`, a method it hard-declined is left out."""
	from central.billing.payments import collection

	currency = frappe.db.get_value("Billing Profile", team, "currency")
	limits = [
		method_limit(m.gateway, currency, m.mandate_max_amount)
		for m in collection.get_methods_left(team, invoice)
	]
	if not limits or None in limits:
		return None
	return max(limits)


def is_within_limit(limit: float | None, amount: float) -> bool:
	"""Whether `amount` is at or under `limit`. No limit takes any amount."""
	return limit is None or frappe.utils.flt(amount) <= limit


def is_within_off_session_limit(team: str, amount: float, invoice: str | None = None) -> bool:
	"""Whether some saved method of the team may take `amount` off-session. For an
	`invoice`, a method it hard-declined does not count."""
	return is_within_limit(off_session_limit(team, invoice), amount)


def is_within_method_limit(method, currency: str | None, amount: float) -> bool:
	"""Whether this Payment Method row may take `amount` off-session."""
	return is_within_limit(method_limit(method.gateway, currency, method.mandate_max_amount), amount)


def is_debit_allowed(team: str) -> bool:
	"""Whether a team's methods may be debited off-session once its credit runs out.

	Prepaid is a promise to keep credit topped up, not a ban on the card behind it, so
	only Manual Checkout (the customer pays by hand) and Action Required (paused over the
	limit) hold a debit back."""
	mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	return mode not in DEBIT_HELD_MODES


def trip(team: str, reason: str, invoice: str | None = None) -> None:
	"""Pause silent auto-charge and raise Action Required. Idempotent — notifies
	once (a team already in action_required is left as-is). The notice quotes the
	limit left for `invoice`, when one tripped it."""
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
		context={"reason": reason, "threshold": off_session_limit(team, invoice)},
		reference_doctype="Billing Profile",
		reference_name=team,
	)


def trip_off_session_debit(team: str, reason: str, invoice: str | None = None) -> None:
	"""Trip Action Required for a team whose method was to be charged off-session. A Manual
	Checkout team already pays by hand, so it keeps its mode."""
	if is_debit_allowed(team):
		trip(team, reason, invoice)


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
		"threshold": shown_limit(team, p.collection_action_reason),
		"choices": list(CUSTOMER_CHOOSABLE),
		"can_return_to_auto": _has_chargeable_method(team),
	}


def shown_limit(team: str, reason: str | None) -> float | None:
	"""The limit the banner quotes. A bill over the limit is read against the oldest
	owed bill, so the banner and the notice agree."""
	invoice = _oldest_owed_invoice(team) if reason == "invoice_over_threshold" else None
	return off_session_limit(team, invoice)


def _oldest_owed_invoice(team: str) -> str | None:
	"""The team's oldest owed bill with something left to collect."""
	from central.billing.doctype.invoice.invoice import owed_filters

	owed = frappe.get_all(
		"Invoice",
		filters=[
			*owed_filters(),
			["team", "=", team],
			["invoice_type", "=", "Billable"],
			["expected_collection", ">", 0],
		],
		order_by="due_date asc, creation asc",
		pluck="name",
		limit=1,
	)
	return owed[0] if owed else None
