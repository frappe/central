# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What the customer picks, on which surface, and which rail it lands on (ADR 0023).

Two rules run this module.

**Stripe takes everything it can.** We are a Stripe India merchant, and Razorpay is
consulted only where that account cannot serve the instrument or the network at
all: it carries no UPI, Stripe has no netbanking product anywhere, and Stripe
registers India card mandates on Visa and Mastercard only. So the split is
mechanical, and a Stripe product change moves a rail without re-opening anything.

**Recharge is not the mandate surface.** Topping up a wallet happens once with the
customer present and no ceiling. A mandate debits later with nobody present, under
the ₹15,000 rule. They offer different instruments, because different instruments
can be saved — netbanking pays once and saves nothing, so it belongs to one surface
and not the other.

We never detect the card network. Stripe Elements iframes the PAN, so the digits
never reach the server. Instead each surface says which networks its rail accepts,
and the customer's own choice is the signal. Once a Payment Method exists its own
`gateway` settles it for life; nothing here is consulted at charge time.
"""

import frappe

RECHARGE = "recharge"
MANDATE = "mandate"

CARD = "Card"
RUPAY_CARD = "RuPay Card"
OTHER_NETWORK_CARD = "Other Network Card"
UPI = "UPI"
UPI_AUTOPAY = "UPI Autopay"
NETBANKING = "Netbanking"

# `currencies = None` means every currency the adapter settles. A tile is never
# labelled "Other cards": a customer holding an unusual Visa would read that as
# theirs and land on a rail that cannot take it, so every tile names its networks.
CATALOGUE = (
	{
		"surface": RECHARGE,
		"instrument": CARD,
		"label": "Card",
		"description": "Visa, Mastercard or Amex",
		"adapter": "Stripe",
		"method_type": None,
		"currencies": None,
		"fallback_reason": None,
	},
	{
		"surface": RECHARGE,
		"instrument": RUPAY_CARD,
		"label": "RuPay card",
		"description": "RuPay runs on a different rail from other cards",
		"adapter": "Razorpay",
		"method_type": None,
		"currencies": ("INR",),
		"fallback_reason": None,
	},
	{
		"surface": RECHARGE,
		"instrument": UPI,
		"label": "UPI",
		"description": "Pay from your bank account",
		"adapter": "Razorpay",
		"method_type": None,
		"currencies": ("INR",),
		"fallback_reason": None,
	},
	{
		"surface": RECHARGE,
		"instrument": NETBANKING,
		"label": "Netbanking",
		"description": "Pay through your bank's own site",
		"adapter": "Razorpay",
		"method_type": None,
		"currencies": ("INR",),
		"fallback_reason": None,
	},
	{
		"surface": MANDATE,
		"instrument": CARD,
		"label": "Card",
		"description": "Visa or Mastercard, charged automatically each month",
		"adapter": "Stripe",
		"method_type": "Card",
		"currencies": None,
		"fallback_reason": None,
	},
	{
		"surface": MANDATE,
		"instrument": OTHER_NETWORK_CARD,
		"label": "RuPay, Amex or Diners card",
		"description": "These networks are saved on a different rail",
		"adapter": "Razorpay",
		"method_type": "Card",
		"currencies": ("INR",),
		"fallback_reason": "Network Unsupported",
	},
	{
		"surface": MANDATE,
		"instrument": UPI_AUTOPAY,
		"label": "UPI",
		"description": "Authorise a UPI mandate once; we debit it each month",
		"adapter": "Razorpay",
		"method_type": "UPI Autopay",
		"currencies": ("INR",),
		"fallback_reason": None,
	},
)

BY_KEY = {(entry["surface"], entry["instrument"]): entry for entry in CATALOGUE}


def get(instrument: str, surface: str = MANDATE) -> dict:
	entry = BY_KEY.get((surface, instrument))
	if not entry:
		frappe.throw(
			frappe._("{0} is not a payment option here.").format(instrument), frappe.ValidationError
		)
	return entry


def gateway_for(instrument: str, currency: str, surface: str = MANDATE) -> str | None:
	"""The enabled gateway that carries this instrument in this currency, if any."""
	from central.billing.api.dashboard._shared import _enabled_gateway_for_currency

	entry = get(instrument, surface)
	if entry["currencies"] and currency not in entry["currencies"]:
		return None
	return _enabled_gateway_for_currency(currency, entry["adapter"])


def available(currency: str, surface: str = MANDATE) -> list[dict]:
	"""The instruments a team billed in `currency` can be offered on this surface.

	An instrument whose gateway is disabled, or which does not exist in the
	currency, is left out rather than shown and refused.
	"""
	offered = []
	for entry in CATALOGUE:
		if entry["surface"] != surface:
			continue
		gateway = gateway_for(entry["instrument"], currency, surface)
		if not gateway:
			continue
		offered.append(
			{
				"instrument": entry["instrument"],
				"label": entry["label"],
				"description": entry["description"],
				"gateway": gateway,
				"adapter_key": entry["adapter"],
				"surface": surface,
			}
		)
	return offered
