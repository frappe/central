# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers for the customer dashboard endpoints.

Team resolution + access gating, currency/gateway lookups, and the line-item
humaniser. Endpoint modules (account/invoices/methods) build on these.
"""

import frappe

from central.billing import authz

# Tier caps (max_spend) are stored in INR; convert to the team's billing currency
# so a EUR/USD team sees a coherent cap-vs-spend comparison.
_FX_TO_INR = {"INR": 1.0, "EUR": 90.0, "USD": 83.0}


def _default_team() -> str | None:
	"""The team to show by default: the caller's own, or — for an operator browsing
	without a team — any team with data, so the portal is never empty/broken."""
	team = authz.get_user_team()
	if not team and authz.is_operator():
		team = frappe.db.get_value("Subscription", {}, "team")
	return team


def _resolve_team(team: str | None, require: str = authz.VIEW) -> str:
	"""The team to serve: the caller's own (default), gated by capability.

	Reads require `billing:view` (the default); pass `require=authz.MANAGE` on a
	mutation endpoint that takes a `team` argument."""
	team = team or _default_team()
	if not team:
		frappe.throw("No billing team in context.", frappe.ValidationError)
	authz.require_capability(team, require)
	return team


def _require_view(team: str) -> str:
	"""Gate a read endpoint whose team is derived from a record (e.g. an invoice)."""
	authz.require_billing_view(team)
	return team


def _require_manage(team: str) -> str:
	"""Gate a mutation whose team is derived from a record (e.g. a payment method)."""
	authz.require_billing_manage(team)
	return team


def _team_clusters(team: str) -> list[str]:
	return [c for c in set(frappe.get_all("Price Lock", {"team": team}, pluck="cluster")) if c]


def _team_currency(team: str) -> str:
	"""A team bills in a single currency: the one set on its Billing Profile.

	Falls back to a price-lock currency (legacy teams whose profile predates the
	currency field) then INR, so reads never break before a profile exists."""
	return (
		frappe.db.get_value("Billing Profile", team, "currency")
		or frappe.db.get_value("Price Lock", {"team": team}, "currency")
		or "INR"
	)


# A team must complete its billing profile — currency + legal name + a billing
# address — before any money moves (top-up, buy credits, add a payment method).
# Currency is the load-bearing field: wallet, payment methods and invoices are
# all denominated in it, so it must be chosen first and then held fixed.
_REQUIRED_PROFILE_FIELDS = (
	"currency", "legal_name", "address_line1", "city", "state", "country", "pincode",
)


def _missing_profile_fields(team: str) -> list[str]:
	"""Required billing-profile fields the team has not filled in yet."""
	if not frappe.db.exists("Billing Profile", team):
		return list(_REQUIRED_PROFILE_FIELDS)
	doc = frappe.get_doc("Billing Profile", team)
	return [f for f in _REQUIRED_PROFILE_FIELDS if not str(doc.get(f) or "").strip()]


def _profile_complete(team: str) -> bool:
	return not _missing_profile_fields(team)


def _require_billing_setup(team: str):
	"""Server-side backstop: refuse money movement until the profile is complete.
	The dashboard also blocks these actions; this guarantees it can't be bypassed."""
	if _missing_profile_fields(team):
		frappe.throw(
			"Complete your billing profile (currency, legal name and address) in "
			"Settings before adding credits or a payment method.",
			frappe.ValidationError,
		)


def _has_money_activity(team: str) -> bool:
	"""True once anything denominated in the team's currency exists — a credit
	ledger entry, a payment method, or an invoice. Currency is locked thereafter,
	so a wallet can't end up holding mixed-currency value."""
	return bool(
		frappe.db.exists("Credit Ledger Entry", {"team": team})
		or frappe.db.exists("Payment Method", {"team": team})
		or frappe.db.exists("Invoice", {"team": team})
	)


def _gateway_for_currency(currency: str) -> str:
	"""Pick the enabled gateway that is the default for this currency.

	Delegates to the canonical resolver so config (is_default row in the
	Payment Gateway Currency child table) is the single source of truth."""
	from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency

	try:
		return resolve_gateway_for_currency(currency)
	except GatewayNotFound:
		frappe.throw(f"No payment gateway configured for {currency} top-ups.", frappe.ValidationError)


def _enabled_gateway_for_currency(currency: str, adapter_key: str) -> str | None:
	"""Name of an enabled gateway with this adapter_key that handles this currency,
	or None. Unlike the default-resolver, this picks by adapter regardless of the
	is_default flag — used when a flow needs a specific rail (PayPal, or the Razorpay
	a Via-Razorpay PayPal row delegates to)."""
	rows = frappe.get_all(
		"Payment Gateway Currency", filters={"currency": currency}, fields=["parent"]
	)
	for r in rows:
		gw = frappe.db.get_value(
			"Payment Gateway", r.parent, ["name", "adapter_key", "is_enabled"], as_dict=True
		)
		if gw and gw.is_enabled and gw.adapter_key == adapter_key:
			return gw.name
	return None


def _paypal_gateway_for_currency(currency: str) -> str:
	"""Enabled PayPal gateway that handles this currency (ADR 0007).

	PayPal is a directly-settled standalone gateway — its own merchant account pays
	us out, so a top-up carries a native PayPal capture id the reconciliation job
	(#21) matches against PayPal's ledger. It need not be the currency default (that
	stays Stripe, which serves card top-ups)."""
	gw = _enabled_gateway_for_currency(currency, "Paypal")
	if gw:
		return gw
	frappe.throw(
		f"PayPal top-ups need an enabled PayPal gateway that handles {currency}.",
		frappe.ValidationError,
	)


def _add_method_gateway(currency: str):
	"""Gateway to add a payment method in this currency.

	Resolves the default gateway for the currency. A Razorpay gateway (adapter_key
	= razorpay) wins over any other default because only Razorpay carries UPI
	Autopay; the adapter drives what rails are shown, not a separate flag."""
	from central.billing.gateways.registry import GatewayNotFound, resolve_gateway_for_currency

	try:
		gw_name = resolve_gateway_for_currency(currency)
	except GatewayNotFound:
		return frappe._dict()

	gw = frappe.db.get_value("Payment Gateway", gw_name, ["name", "adapter_key"], as_dict=True)
	if gw and gw.adapter_key == "Razorpay":
		return gw

	# The default gateway is not Razorpay — but if an enabled Razorpay gateway
	# also handles this currency (non-default), prefer it for UPI.
	rzp = frappe.db.get_value(
		"Payment Gateway",
		{"adapter_key": "Razorpay", "is_enabled": 1},
		["name", "adapter_key"],
		as_dict=True,
		order_by="creation asc",
	)
	if rzp:
		rzp_currencies = frappe.get_all(
			"Payment Gateway Currency", {"parent": rzp.name, "currency": currency}, pluck="name"
		)
		if rzp_currencies:
			return rzp

	return gw or frappe._dict()


def _from_inr(amount: float, currency: str) -> float:
	return frappe.utils.flt(frappe.utils.flt(amount) / _FX_TO_INR.get(currency, 1.0), 2)


def _describe_line(team: str, li) -> dict:
	"""Turn a stored line item into a human-readable charge row.

	Resource slugs and plan IDs mean nothing to a customer, so we resolve the
	plan/add-on TITLE and spell out what drove the charge: a plan's monthly fee
	(prorated days), or a metered overage above the plan's included allowance.
	"""
	row = {
		"resource_type": li.resource_type, "plan": li.plan,
		"subscription_resource": li.subscription_resource,
		"days": li.days, "quantity": li.quantity, "rate": li.rate, "amount": li.amount,
		"unit": li.unit,
	}
	if li.resource_type == "bundle":
		title = frappe.db.get_value("Plan", li.plan, "title") if li.plan else None
		row["item"] = title or li.plan or "Subscription plan"
		row["kind"] = "Plan"
		row["detail"] = f"{li.days} day(s) this period" if li.days else None
	else:
		addon = frappe.db.get_value("Add-on", {"resource_type": li.resource_type}, ["title"])
		row["item"] = addon or f"{li.resource_type.title()} overage"
		row["kind"] = "Overage"
		# Surface the included allowance the usage ran past, so the bill is legible.
		allowance = frappe.db.get_value(
			"Usage Rollup",
			{"team": team, "resource_id": li.subscription_resource, "resource_type": li.resource_type},
			"locked_allowance",
		)
		unit = li.unit or "units"
		if allowance is not None:
			row["detail"] = f"{frappe.utils.flt(li.quantity):g} {unit} over {frappe.utils.flt(allowance):g} {unit} included"
		else:
			row["detail"] = f"{frappe.utils.flt(li.quantity):g} {unit} metered"
	return row
