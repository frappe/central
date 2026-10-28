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
from frappe import _
from frappe.utils.translations import _lt

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


# Declines a later retry cannot fix: the card is wrong, gone or barred, or the
# customer must be present. A shortfall or a generic bank refusal can clear in days.
HARD_CODES = tuple(code for code in TERMINAL_CODES if code != "card_declined")
HARD_DECLINE_CODES = (
	"lost_card",
	"stolen_card",
	"pickup_card",
	"fraudulent",
	"restricted_card",
	"invalid_account",
	"do_not_try_again",
	"revocation_of_authorization",
	"revocation_of_all_authorizations",
	"merchant_blacklist",
)

# What a decline means to the person whose card it was. Gateway codes and their
# raw messages are written for us, not for them: "authentication_failed" and
# "do_not_honor" tell a customer nothing about what to do next. Anything not
# listed falls back to "we couldn't complete this payment", which is vague but
# never wrong — inventing a specific reason we don't have is worse.
_CUSTOMER_REASON = {
	"expired_card": _lt("Your card has expired"),
	"incorrect_number": _lt("The card number was wrong"),
	"incorrect_cvc": _lt("The security code was wrong"),
	"card_declined": _lt("Your bank declined the payment"),
	"insufficient_funds": _lt("There wasn't enough balance"),
	"card_not_supported": _lt("Your bank doesn't allow this kind of payment"),
	"authentication_failed": _lt("The bank's verification step didn't complete"),
	"do_not_honor": _lt("Your bank declined the payment"),
	"payment_intent_mandate_invalid": _lt("Your auto-pay approval is no longer valid"),
	"india_recurring_payment_mandate_canceled": _lt("Your auto-pay approval was cancelled"),
	"transaction_not_approved": _lt("Your bank didn't approve the auto-payment"),
}

# Ambiguous failures may still settle. Saying "failed" of one is a lie we would
# have to take back, so they are named as unresolved.
_UNRESOLVED = _lt("We're still confirming this payment with your bank")


def customer_reason(failure_code: str | None, fallback: str | None = None) -> str:
	"""The decline, said to the customer whose payment it was.

	Ambiguity is checked FIRST and deliberately: a timeout may still settle at the
	bank, so naming a cause for it ("the bank didn't respond") tells the customer
	the payment failed when we do not know that. Getting this order wrong is how a
	customer pays an invoice twice.
	"""
	code = (failure_code or "").lower()
	if code in AMBIGUOUS_CODES:
		return str(_UNRESOLVED)
	if code in _CUSTOMER_REASON:
		return str(_CUSTOMER_REASON[code])
	# Never surface the gateway's own string: it is written for an operator and
	# frequently names internals a customer cannot act on.
	return _("We couldn't complete this payment")


# Why Central refused a mandate confirmation. Nothing about the customer's bank.
SIGNATURE_INVALID = "signature_invalid"
ORDER_MISMATCH = "order_mismatch"
PAYMENT_NOT_AUTHORISED = "payment_not_authorised"
MANDATE_REFUSALS = (SIGNATURE_INVALID, ORDER_MISMATCH, PAYMENT_NOT_AUTHORISED)


def failure_fields(failure: dict) -> dict:
	"""The failure columns a record keeps, from a decline shaped like `charges._extract_failure`.
	A failure the gateway gave no code for still gets one, so every failure can be grouped."""
	return {
		"failure_code": failure.get("failure_code") or "payment_failed",
		"decline_code": failure.get("decline_code"),
		"failure_reason": (failure.get("failure_reason") or "")[:140] or None,
	}


def method_failure_message(
	failure_code: str | None, decline_code: str | None = None, method_type: str = "Card"
) -> str:
	"""Why a payment method could not be added, and what the customer can do instead. The
	bank's decline code is the more specific reason, so it is used when we can word it."""
	if failure_code in MANDATE_REFUSALS:
		return _("The mandate authorisation could not be confirmed. Try adding it again.")
	code = decline_code if (decline_code or "").lower() in _CUSTOMER_REASON else failure_code
	if method_type == "Card":
		return _("{0}. Try another card, or add credit to your account instead.").format(
			customer_reason(code)
		)
	return _("{0}. Try again, or add credit to your account instead.").format(customer_reason(code))


def is_mandate_failure(failure_code: str | None) -> bool:
	"""True where the mandate, not the card, is what failed."""
	return (failure_code or "").lower() in MANDATE_CODES


def is_terminal(failure_code: str | None) -> bool:
	"""True only for a decline we know is final. An unrecognised code is treated as
	ambiguous, because the safe reading of "we don't know" is "don't charge again"."""
	code = (failure_code or "").lower()
	return code in TERMINAL_CODES or code in MANDATE_CODES


def is_retryable_later(failure_code: str | None, decline_code: str | None) -> bool:
	"""True where charging the same method again on a later day can succeed.

	An ambiguous failure may still settle, so charging it again could charge twice."""
	code, reason = (failure_code or "").lower(), (decline_code or "").lower()
	if code in AMBIGUOUS_CODES or code in HARD_CODES or code in MANDATE_CODES:
		return False
	return reason not in HARD_DECLINE_CODES and reason not in HARD_CODES


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
