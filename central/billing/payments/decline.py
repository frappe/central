# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Which declines are final, and what we may do about them (ADR 0022).

Only a **terminal** decline justifies moving a customer to another rail. The card
was refused and will be refused again, so offering the alternative costs nothing.
An ambiguous failure is the opposite: a timeout or an abandoned 3DS may still
settle at the gateway, and charging a second rail on top of it is how one invoice
gets paid twice. Those are left to reconciliation, which can go and ask.

The distinction is worth its own module because getting it wrong is not a UX
regression — it is a double charge.
"""

import frappe

# The card is refused. Nothing about retrying it changes that.
TERMINAL_CODES = (
	"card_declined",
	"card_not_supported",
	"authentication_failed",
	"expired_card",
	"incorrect_number",
	"incorrect_cvc",
)

# The outcome is unknown: the money may yet move. Never fall back on these.
AMBIGUOUS_CODES = (
	"processing",
	"processing_error",
	"timeout",
	"gateway_timeout",
	"authentication_abandoned",
)


# The standing permission is gone or was refused at the bank. The card itself may
# be perfectly good, so these are not declines to hold against it — the method is
# retired and the customer is asked to authorise again (ADR 0023 §7).
MANDATE_CODES = (
	"payment_intent_mandate_invalid",
	"india_recurring_payment_mandate_canceled",
	"transaction_not_approved",
)


def is_mandate_failure(failure_code: str | None) -> bool:
	"""True where the mandate, not the card, is what failed."""
	return (failure_code or "").lower() in MANDATE_CODES


def is_terminal(failure_code: str | None) -> bool:
	"""True only for a decline we know is final. An unrecognised code is treated as
	ambiguous, because the safe reading of "we don't know" is "don't charge again"."""
	code = (failure_code or "").lower()
	return code in TERMINAL_CODES or code in MANDATE_CODES


def fallback_enabled() -> bool:
	"""Whether offering the other rail is switched on. Routing is configuration, so
	the bet on one gateway can be reversed without a deploy."""
	return bool(frappe.db.get_single_value("Billing Settings", "enable_gateway_fallback"))


def recent_terminal_decline(team: str, gateway: str | None = None, within_hours: int = 24) -> dict | None:
	"""The team's most recent attempt that a gateway finally refused, if it is recent.

	This is the server's own answer to "did a card just fail?", and it exists because
	the client is about to claim exactly that. `fallback_reason` is a field we report
	on when judging one rail against another, so it cannot be whatever a caller says
	it is — a customer who simply prefers UPI would otherwise be recorded as a Stripe
	failure and quietly move the number.
	"""
	since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-within_hours)
	filters = {"team": team, "status": "Failed", "creation": [">", since]}
	if gateway:
		filters["gateway"] = gateway
	for attempt in frappe.get_all(
		"Payment Attempt",
		filters=filters,
		fields=["name", "gateway", "failure_code"],
		order_by="creation desc",
		limit=5,
	):
		if is_terminal(attempt.failure_code) and not is_mandate_failure(attempt.failure_code):
			return attempt
	return None


def alternate_rail(team: str, currency: str, failed_gateway: str) -> dict | None:
	"""An instrument on a different gateway that this team could pay with instead.

	Returns the tile to offer, not a charge: the customer taps once, with the amount
	already filled in, and never meets an empty second card form. None where the
	currency has no second rail, or fallback is switched off.
	"""
	from central.billing.payments import instruments

	if not fallback_enabled():
		return None
	for tile in instruments.available(currency, instruments.MANDATE):
		if tile["gateway"] != failed_gateway:
			return tile
	return None
