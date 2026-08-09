# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What the customer picks, and which rail it lands on (ADR 0022).

An Indian customer adding a payment method sees four tiles — UPI, Card, RuPay
card, Netbanking. That is an ordinary Indian checkout, and it is also how we learn
which gateway to register on, because **the instrument picks the gateway**. We
never detect the card network ourselves: Stripe Elements iframes the PAN, so the
digits never reach the server, and the customer already knows which card they are
holding.

Once a Payment Method exists its own `gateway` settles it for the rest of its
life. Nothing here is consulted at charge time.
"""

import frappe

CARD = "Card"
RUPAY_CARD = "RuPay Card"
UPI_AUTOPAY = "UPI Autopay"
NETBANKING = "Netbanking"

# The tile is labelled "RuPay card", never "Other cards": a customer holding an
# unusual Visa would read "Other" as theirs and land on a rail that cannot take it.
CATALOGUE = (
	{
		"instrument": CARD,
		"label": "Card",
		"description": "Visa, Mastercard, Amex or Diners",
		"adapter": "Stripe",
		"method_type": "Card",
		"recurring": True,
		"currencies": None,  # every currency Stripe settles
		"fallback_reason": None,
	},
	{
		"instrument": RUPAY_CARD,
		"label": "RuPay card",
		"description": "RuPay runs on a different rail from other cards",
		"adapter": "Razorpay",
		"method_type": "Card",
		"recurring": True,
		"currencies": ("INR",),
		"fallback_reason": "Rupay",
	},
	{
		"instrument": UPI_AUTOPAY,
		"label": "UPI",
		"description": "Pay from your bank account with a UPI mandate",
		"adapter": "Razorpay",
		"method_type": "UPI Autopay",
		"recurring": True,
		"currencies": ("INR",),
		"fallback_reason": None,
	},
	{
		"instrument": NETBANKING,
		"label": "Netbanking",
		"description": "One-time payment from your bank; nothing is saved",
		"adapter": "Razorpay",
		"method_type": None,  # nothing is saved, so no Payment Method is created
		"recurring": False,
		"currencies": ("INR",),
		"fallback_reason": None,
	},
)

BY_INSTRUMENT = {entry["instrument"]: entry for entry in CATALOGUE}


def get(instrument: str) -> dict:
	entry = BY_INSTRUMENT.get(instrument)
	if not entry:
		frappe.throw(frappe._("Unknown payment instrument {0}.").format(instrument), frappe.ValidationError)
	return entry


def gateway_for(instrument: str, currency: str) -> str | None:
	"""The enabled gateway that carries this instrument in this currency, if any."""
	from central.billing.api.dashboard._shared import _enabled_gateway_for_currency

	entry = get(instrument)
	if entry["currencies"] and currency not in entry["currencies"]:
		return None
	return _enabled_gateway_for_currency(currency, entry["adapter"])


def available(currency: str) -> list[dict]:
	"""The instruments a team billed in `currency` can actually be offered.

	An instrument whose gateway is disabled, or which does not exist in the
	currency, is left out rather than shown and refused.
	"""
	offered = []
	for entry in CATALOGUE:
		gateway = gateway_for(entry["instrument"], currency)
		if not gateway:
			continue
		offered.append(
			{
				"instrument": entry["instrument"],
				"label": entry["label"],
				"description": entry["description"],
				"gateway": gateway,
				"adapter_key": entry["adapter"],
				"recurring": entry["recurring"],
			}
		)
	return offered
