# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helpers for the customer dashboard endpoints.

Team resolution + access gating, currency/gateway lookups, and the line-item
humaniser. Endpoint modules (account/invoices/methods) build on these.
"""

import frappe

from central.billing.platform.security import get_user_team, is_billing_admin, require_team_access

# Tier caps (max_spend) are stored in INR; convert to the team's billing currency
# so a EUR/USD team sees a coherent cap-vs-spend comparison.
_FX_TO_INR = {"INR": 1.0, "EUR": 90.0, "USD": 83.0}


def _default_team() -> str | None:
	"""The team to show by default: the caller's own, or — for an admin browsing
	without a team — any team with data, so the portal is never empty/broken."""
	team = get_user_team()
	if not team and is_billing_admin():
		team = frappe.db.get_value("Subscription", {}, "team")
	return team


def _resolve_team(team: str | None) -> str:
	"""The team to serve: the caller's own (default), gated by access."""
	team = team or _default_team()
	if not team:
		frappe.throw("No billing team in context.", frappe.ValidationError)
	require_team_access(team)
	return team


def _team_clusters(team: str) -> list[str]:
	return [c for c in set(frappe.get_all("Price Lock", {"team": team}, pluck="cluster")) if c]


def _team_currency(team: str) -> str:
	"""A team bills in a single currency — read it off any of its price-locks."""
	return frappe.db.get_value("Price Lock", {"team": team}, "currency") or "INR"


def _gateway_for_currency(currency: str) -> str:
	"""Pick the enabled gateway that settles in this currency (e.g. EUR → Stripe,
	INR → Razorpay), preferring the one flagged default-for-currency. A team must
	never be sent to a gateway that can't take its currency."""
	gw = (frappe.db.get_value("Payment Gateway",
			{"currency": currency, "is_enabled": 1, "is_default_for_currency": 1}, "name")
		or frappe.db.get_value("Payment Gateway",
			{"currency": currency, "is_enabled": 1}, "name"))
	if not gw:
		frappe.throw(f"No payment gateway configured for {currency} top-ups.", frappe.ValidationError)
	return gw


def _add_method_gateway(currency: str):
	"""Gateway to add a payment method in this currency.

	A Razorpay gateway (if one exists for the currency) wins, because only
	Razorpay carries UPI Autopay — picking by *adapter* not by
	`is_default_for_currency`, since the demo flags a Stripe-INR gateway as the
	INR default which must not hide UPI. Otherwise the currency's gateway
	(Stripe = card only)."""
	rzp = frappe.db.get_value(
		"Payment Gateway",
		{"currency": currency, "adapter_key": "razorpay", "is_enabled": 1},
		["name", "adapter_key"], as_dict=True, order_by="is_default_for_currency desc",
	)
	if rzp:
		return rzp
	return frappe.db.get_value(
		"Payment Gateway", {"currency": currency, "is_enabled": 1},
		["name", "adapter_key"], as_dict=True, order_by="is_default_for_currency desc",
	) or frappe._dict()


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


def ensure_billing_team_field():
	"""A User field linking a Billing User to their team (run from after_migrate)."""
	if not frappe.db.exists("Custom Field", "User-billing_team"):
		frappe.get_doc({
			"doctype": "Custom Field", "dt": "User", "fieldname": "billing_team",
			"label": "Billing Team", "fieldtype": "Data", "insert_after": "username",
		}).insert(ignore_permissions=True)
