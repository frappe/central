# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment-method dashboard endpoints: list/options, card + Razorpay-recurring
setup, and fallback-order management. Gateway secrets are never returned.
"""

import frappe

from central.billing import authz
from central.billing.api.dashboard._shared import (
	_add_method_gateway,
	_require_billing_setup,
	_require_manage,
	_resolve_team,
	_team_currency,
)


@frappe.whitelist()
def list_payment_methods(team: str | None = None) -> list[dict]:
	"""Payment methods — display fields only; gateway secrets are never returned."""
	team = _resolve_team(team)
	return frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": ["!=", "Cancelled"]},
		fields=["name", "method_type", "status", "display_label", "is_default", "priority",
				"reauth_required", "expiry_month", "expiry_year"],
		order_by="priority asc, creation asc",
	)


@frappe.whitelist()
def get_payment_method_options(team: str | None = None) -> dict:
	"""What the team can set up, resolved from their billing currency: card + UPI
	on Razorpay (INR), card-only on Stripe (USD/EUR). UPI is gated by the
	₹1,00,000 recurring limit."""
	team = _resolve_team(team)
	currency = _team_currency(team)
	gw = _add_method_gateway(currency)

	if gw.get("adapter_key") == "Razorpay":
		from central.billing.payments import mandates

		elig = mandates.upi_eligibility(team)
		return {"gateway": gw.name, "adapter_key": "Razorpay", "currency": currency,
				"methods": ["Card", "UPI Autopay"], "allow_upi": elig["eligible"],
				"upi_block_reason": elig["reason"], "upi_limit": elig["limit"]}

	publishable_key = None
	if gw.get("adapter_key") == "Stripe":
		from central.billing.gateways.registry import get_adapter

		publishable_key = get_adapter(frappe.get_doc("Payment Gateway", gw.name)).get_credential("api_key")
	return {"gateway": gw.get("name"), "adapter_key": gw.get("adapter_key"), "currency": currency,
			"methods": ["Card"], "allow_upi": False, "upi_block_reason": None, "upi_limit": None,
			"publishable_key": publishable_key}


@frappe.whitelist(methods=["POST"])
def initiate_card_setup(team: str | None = None, gateway: str | None = None) -> dict:
	"""Begin adding a card (gateway SetupIntent → client_secret). Real PAN is
	collected client-side by the gateway SDK (PCI), never by our server."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	from central.billing.payments import payments

	return payments.initiate_payment_method_setup(team, gateway)


@frappe.whitelist(methods=["POST"])
def confirm_card(payment_method: str | None = None, gateway_method_id: str | None = None,
				 display_label: str | None = None, expiry_month: int | None = None,
				 expiry_year: int | None = None) -> dict:
	"""Confirm a card the gateway SDK tokenised — runs the micro-charge validation."""
	from central.billing.payments import payments

	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	method = payments.confirm_payment_method(
		payment_method, gateway_method_id=gateway_method_id, display_label=display_label,
		expiry_month=expiry_month, expiry_year=expiry_year)
	return {"payment_method": method.name, "status": method.status}


@frappe.whitelist(methods=["POST"])
def add_demo_card(team: str | None = None, gateway: str | None = None,
				  display_label: str = "Visa ····4242", expiry_month: int = 12,
				  expiry_year: int = 2030) -> dict:
	"""Demo convenience: register an active card without a live gateway round-trip.
	(Production uses initiate_card_setup + confirm_card with the gateway SDK.)"""
	team = _resolve_team(team, authz.MANAGE)
	from central.billing.payments import payments

	name = frappe.get_doc({
		"doctype": "Payment Method", "team": team, "gateway": gateway, "method_type": "Card",
		"status": "Active", "display_label": display_label, "gateway_method_id": f"pm_{frappe.generate_hash(6)}",
		"gateway_customer_id": f"cus_{team}", "expiry_month": expiry_month, "expiry_year": expiry_year,
		"validated_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True).name
	payments.densify_priorities(team)  # append at the end of the fallback order
	return {"payment_method": name, "status": "Active"}


@frappe.whitelist(methods=["POST"])
def setup_payment_method_order(team: str | None = None, gateway: str | None = None,
							   method_type: str = "UPI Autopay") -> dict:
	"""Begin adding a Razorpay recurring method — UPI Autopay mandate (ceiling =
	trust-tier cap) or a card token. Returns the order handles the UI runs
	Razorpay Checkout against (#08)."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	gw = gateway or _add_method_gateway(_team_currency(team)).get("name")
	from central.billing.payments import mandates

	if method_type == "Card":
		return mandates.setup_card(team, gw)
	return mandates.setup_mandate(team, gw)


@frappe.whitelist(methods=["POST"])
def confirm_payment_method_order(payment_method: str | None = None, razorpay_payment_id: str | None = None,
								 razorpay_order_id: str | None = None, razorpay_signature: str | None = None,
								 razorpay_token_id: str | None = None) -> dict:
	"""Confirm the Razorpay Checkout callback — verifies the signature, activates
	the mandate. Real gateway verification, not a stub."""
	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	from central.billing.payments import mandates

	method = mandates.confirm_mandate(payment_method, {
		"razorpay_payment_id": razorpay_payment_id, "razorpay_order_id": razorpay_order_id,
		"razorpay_signature": razorpay_signature, "razorpay_token_id": razorpay_token_id,
	})
	return {"payment_method": method.name, "status": method.status}


@frappe.whitelist(methods=["POST"])
def remove_payment_method(payment_method: str | None = None) -> dict:
	"""Remove a card/mandate; promotes another active method to default."""
	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	from central.billing.payments import payments

	return payments.delete_payment_method(payment_method)


@frappe.whitelist(methods=["POST"])
def set_default_payment_method(payment_method: str | None = None) -> dict:
	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	from central.billing.payments import payments

	doc = payments.set_default_payment_method(payment_method)
	return {"payment_method": doc.name, "is_default": doc.is_default, "priority": doc.priority}


@frappe.whitelist(methods=["POST"])
def reorder_payment_methods(team: str | None = None, ordered: list | str | None = None) -> dict:
	"""Set the team's fallback order (primary→backups) from a top-first list."""
	team = _resolve_team(team, authz.MANAGE)
	from central.billing.payments import payments

	return payments.reorder_payment_methods(team, ordered)
