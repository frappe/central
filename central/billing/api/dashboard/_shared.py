# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers for the customer dashboard endpoints.

Team resolution + access gating, currency/gateway lookups, and the line-item
humaniser. Endpoint modules (account/invoices/methods) build on these.
"""

import frappe

from central.billing import authz
from central.billing.catalog.subscriptions import team_active_segments

# Tier caps (max_spend) are stored in INR; convert to the team's billing currency
# so a USD team sees a coherent cap-vs-spend comparison.
_FX_TO_INR = {"INR": 1.0, "USD": 83.0}


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


def _billing_group_titles(names) -> dict:
	"""name -> title for a batch of Billing Group ids, one query regardless of how
	many rows reference them (list_subscriptions / list_invoices resolve their
	`billing_group` link to a display title this way instead of one lookup per row)."""
	names = [n for n in set(names) if n]
	if not names:
		return {}
	return {
		g.name: g.title
		for g in frappe.get_all("Billing Group", filters={"name": ["in", names]}, fields=["name", "title"])
	}


def _team_resource_count(team: str) -> int:
	"""How many resources the team is running: its open billing segments (ADR 0010),
	preset and composed alike (#86)."""
	return len(team_active_segments(team))


def _team_clusters(team: str) -> list[str]:
	return sorted({s.cluster for s in team_active_segments(team) if s.cluster})


def _team_currency(team: str) -> str:
	"""A team bills in a single currency: the one set on its Billing Profile.

	Falls back to an open-segment currency (legacy teams whose profile predates the
	currency field) then INR, so reads never break before a profile exists."""
	seg_currency = next((s.currency for s in team_active_segments(team) if s.currency), None)
	return frappe.db.get_value("Billing Profile", team, "currency") or seg_currency or "INR"


# A team must complete its billing profile — currency + legal name + a billing
# address — before any money moves (top-up, buy credits, add a payment method).
# Currency is the load-bearing field: wallet, payment methods and invoices are
# all denominated in it, so it must be chosen first and then held fixed.
#
# State and pincode are deliberately NOT required: they're irrelevant for foreign
# customers, and for India the state is only enforced when a GSTIN is entered
# (see BillingProfile.validate_india_state).
_REQUIRED_PROFILE_FIELDS = (
	"currency", "legal_name", "address_line1", "city", "country",
)
_PROFILE_FIELD_LABELS = {
	"currency": "currency",
	"legal_name": "legal name",
	"address_line1": "address line 1",
	"city": "city",
	"country": "country",
}


def currency_for_country(country: str | None) -> str:
	"""Billing currency follows the customer's country: India bills in INR, every
	other country in USD. Derived, not chosen — so a customer can't pick a currency
	that mismatches where they are."""
	from central.billing.india_gst import INDIA

	return "INR" if (country or "").strip() == INDIA else "USD"


def _missing_profile_fields(team: str) -> list[str]:
	"""Required billing-profile fields the team has not filled in yet."""
	if not frappe.db.exists("Billing Profile", team):
		return list(_REQUIRED_PROFILE_FIELDS)
	doc = frappe.get_doc("Billing Profile", team)
	return [f for f in _REQUIRED_PROFILE_FIELDS if not str(doc.get(f) or "").strip()]


def _profile_complete(team: str) -> bool:
	return not _missing_profile_fields(team)


def _missing_profile_labels(team: str) -> list[str]:
	return [_PROFILE_FIELD_LABELS.get(field, field) for field in _missing_profile_fields(team)]


def require_billing_profile(team: str, action: str):
	"""Refuse `action` until the team's billing profile is complete.

	Server-side backstop for anything that needs billing set up first (money
	movement, provisioning a billable resource). The dashboard also blocks these;
	this guarantees it can't be bypassed. `action` completes the sentence
	"… before you can {action}"."""
	missing = _missing_profile_labels(team)
	if missing:
		frappe.throw(
			f"Complete your billing profile before you can {action}. "
			f"Missing: {', '.join(missing)}.",
			frappe.ValidationError,
		)


def _require_billing_setup(team: str):
	"""Server-side backstop: refuse money movement until the profile is complete."""
	require_billing_profile(team, "add credits or a payment method")


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


def _card_gateway(currency: str) -> str | None:
	"""The gateway that saves cards for this currency. Saved cards are a Stripe-only
	rail (ADR 0005) in every currency — INR included, where Razorpay handles only the
	UPI Autopay e-mandate. Returns an enabled Stripe gateway that handles the
	currency, or None if there is no card rail for it."""
	return _enabled_gateway_for_currency(currency, "Stripe")


def _from_inr(amount: float, currency: str) -> float:
	return frappe.utils.flt(frappe.utils.flt(amount) / _FX_TO_INR.get(currency, 1.0), 2)


def _describe_line(team: str, li) -> dict:
	"""Turn a stored line item into a human-readable charge row.

	Resource slugs and plan IDs mean nothing to a customer, so we resolve the
	plan TITLE and spell out what drove the charge: a plan's monthly fee
	(prorated days), or a metered overage above the plan's included allowance.
	"""
	from central.billing.revenue.metering import _metered_plan_for
	row = {
		"resource_type": li.resource_type, "plan": li.plan,
		"subscription_resource": li.subscription_resource,
		"days": li.days, "hours": li.hours, "quantity": li.quantity,
		"rate": li.rate, "amount": li.amount, "unit": li.unit,
		"charge_date": li.charge_date,
	}
	if li.resource_type == "bundle":
		title = frappe.db.get_value("Plan", li.plan, "title") if li.plan else None
		row["item"] = title or li.plan or "Subscription plan"
		row["kind"] = "Plan"
		# Hourly lines come from a churn day (multiple resizes within 24h): they're
		# tied to one calendar date, so name it. Daily lines span a range within the
		# period — the invoice already carries the period dates, so no suffix.
		if li.unit == "hour" and li.hours:
			hours = f"{frappe.utils.flt(li.hours):g} hour(s)"
			on = f" on {frappe.utils.getdate(li.charge_date).strftime('%-d %b')}" if li.charge_date else ""
			row["detail"] = f"{hours}{on}"
		elif li.days:
			row["detail"] = f"{li.days} day(s)"
		else:
			row["detail"] = None
	else:
		metered_plan = _metered_plan_for(li.resource_type)
		title = frappe.db.get_value("Plan", metered_plan.name, "title") if metered_plan else None
		row["item"] = title or f"{li.resource_type.title()} overage"
		row["kind"] = "Overage"
		# Surface the included allowance the usage ran past, so the bill is legible.
		allowance = frappe.db.get_value(
			"Usage Rollup",
			{"team": team, "resource_id": li.subscription_resource, "resource_type": li.resource_type},
			"locked_allowance",
		)
		# li.quantity is the BILLABLE overage (usage already minus the allowance). Spell
		# out the metered story so the charge is legible: total used, what was included,
		# and the units actually billed (used − included). Unit is a plain label (Nos, GB).
		unit = li.unit or "units"
		billed = frappe.utils.flt(li.quantity)
		allowance = frappe.utils.flt(allowance)
		if allowance > 0:
			# Legacy plans that still carry a free tier: show used vs included vs billed.
			row["detail"] = (
				f"Metered · {_qty(billed + allowance)} {unit} used · "
				f"{_qty(billed)} billed over {_qty(allowance)} included"
			)
		else:
			# No free tier — every used unit is billed at the per-unit rate.
			row["detail"] = f"Metered · {_qty(billed)} {unit} used"
	return row


def _qty(value) -> str:
	"""Format a metered quantity with thousands separators (90,000), keeping up to two
	decimals only when the count is fractional (e.g. GB)."""
	value = frappe.utils.flt(value)
	return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
