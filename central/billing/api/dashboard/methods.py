# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Payment-method dashboard endpoints: list/options, card + Razorpay-recurring
setup, and fallback-order management. Gateway secrets are never returned.
"""

import frappe
from frappe import _

from central.billing import authz
from central.billing.api.dashboard._shared import (
	_add_method_gateway,
	_card_gateway,
	_enabled_gateway_for_currency,
	_require_billing_setup,
	_require_manage,
	_resolve_team,
	_team_currency,
)


@frappe.whitelist()
def list_payment_methods(team: str | None = None) -> list[dict]:
	"""Payment methods — display fields only; gateway secrets are never returned.

	Hides Cancelled methods and ones still mid-setup (Pending Validation): until a
	card clears the micro-charge it isn't usable, isn't in the charge order, and
	would only confuse the list (it has no label/expiry yet)."""
	team = _resolve_team(team)
	return frappe.get_all(
		"Payment Method",
		filters={"team": team, "status": ["not in", ["Cancelled", "Pending Validation"]]},
		fields=[
			"name",
			"method_type",
			"status",
			"display_label",
			"is_default",
			"priority",
			"reauth_required",
			"expiry_month",
			"expiry_year",
		],
		order_by="priority asc, creation asc",
	)


@frappe.whitelist()
def get_payment_method_options(team: str | None = None) -> dict:
	"""What the team can set up, resolved from their billing currency (ADR 0022).

	The customer picks an instrument and the instrument picks the gateway: cards go
	to Stripe in every currency, and RuPay, UPI Autopay and netbanking to Razorpay,
	which carries what Stripe India cannot. An INR team therefore sees four tiles;
	elsewhere there is only the card.

	`instruments` is the tile list. `methods` is the older flat list of what can be
	saved, kept for callers that have not moved to tiles yet."""
	team = _resolve_team(team)
	currency = _team_currency(team)
	from central.billing.payments import instruments as instrument_catalogue

	tiles = instrument_catalogue.available(currency)

	methods: list[str] = []
	publishable_key = None
	card_gw = _card_gateway(currency)
	if card_gw:
		from central.billing.gateways.registry import get_adapter

		publishable_key = get_adapter(frappe.get_doc("Payment Gateway", card_gw)).get_credential("api_key")
		methods.append("Card")

	# UPI Autopay is a Razorpay e-mandate (INR), offered only where an enabled
	# Razorpay gateway handles the currency — independent of the card rail above.
	upi = {"allow_upi": False, "upi_block_reason": None, "upi_limit": None}
	if _enabled_gateway_for_currency(currency, "Razorpay"):
		from central.billing.payments import mandates

		elig = mandates.upi_eligibility(team)
		methods.append("UPI Autopay")
		upi = {"allow_upi": elig["eligible"], "upi_block_reason": elig["reason"], "upi_limit": elig["limit"]}

	return {
		"gateway": card_gw,
		"adapter_key": "Stripe" if card_gw else None,
		"currency": currency,
		"instruments": tiles,
		"methods": methods,
		"publishable_key": publishable_key,
		**upi,
	}


@frappe.whitelist(methods=["POST"])
def initiate_card_setup(team: str | None = None, gateway: str | None = None) -> dict:
	"""Begin adding a card (gateway SetupIntent → client_secret). Real PAN is
	collected client-side by the gateway SDK (PCI), never by our server."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	# Saved cards are a Stripe-only rail (ADR 0005), so resolve the currency's Stripe
	# gateway — for INR that's the Stripe gateway, not the Razorpay currency default.
	gateway = gateway or _card_gateway(_team_currency(team))
	from central.billing.payments import payments

	return payments.initiate_payment_method_setup(team, gateway)


@frappe.whitelist(methods=["POST"])
def confirm_card(
	payment_method: str | None = None,
	gateway_method_id: str | None = None,
	display_label: str | None = None,
	expiry_month: int | None = None,
	expiry_year: int | None = None,
	gateway_mandate_id: str | None = None,
	card_network: str | None = None,
) -> dict:
	"""Confirm a card the gateway SDK tokenised — runs the micro-charge validation.

	`gateway_mandate_id` is present where the currency required a mandate at setup
	(India); later off-session debits quote it."""
	from central.billing.payments import payments

	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	method = payments.confirm_payment_method(
		payment_method,
		gateway_method_id=gateway_method_id,
		display_label=display_label,
		expiry_month=expiry_month,
		expiry_year=expiry_year,
		gateway_mandate_id=gateway_mandate_id,
		card_network=card_network,
	)
	return {"payment_method": method.name, "status": method.status}


@frappe.whitelist(methods=["POST"])
def add_demo_card(
	team: str | None = None,
	gateway: str | None = None,
	display_label: str = "Visa ····4242",
	expiry_month: int = 12,
	expiry_year: int = 2030,
) -> dict:
	"""Demo convenience: register an active card without a live gateway round-trip.
	(Production uses initiate_card_setup + confirm_card with the gateway SDK.)"""
	team = _resolve_team(team, authz.MANAGE)
	from central.billing.payments import payments

	name = (
		frappe.get_doc(
			{
				"doctype": "Payment Method",
				"team": team,
				"gateway": gateway,
				"method_type": "Card",
				"status": "Active",
				"display_label": display_label,
				"gateway_method_id": f"pm_{frappe.generate_hash(6)}",
				"gateway_customer_id": f"cus_{team}",
				"expiry_month": expiry_month,
				"expiry_year": expiry_year,
				"validated_at": frappe.utils.now_datetime(),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	payments.densify_priorities(team)  # append at the end of the fallback order
	return {"payment_method": name, "status": "Active"}


@frappe.whitelist(methods=["POST"])
def setup_payment_method_order(
	team: str | None = None,
	gateway: str | None = None,
	method_type: str = "UPI Autopay",
	contact: str | None = None,
	instrument: str | None = None,
) -> dict:
	"""Begin adding a Razorpay recurring method — a UPI Autopay mandate (ceiling =
	trust-tier cap) or a RuPay card token.

	`instrument` is what the customer tapped, and it decides the rail (ADR 0022);
	the gateway is resolved from it rather than from the currency default. Callers
	that predate the tiles still pass `method_type`. `contact` is the phone the UI
	collects inline for a card mandate when the billing profile has none (Razorpay
	requires a customer contact for recurring cards)."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	currency = _team_currency(team)
	from central.billing.payments import instruments as instrument_catalogue
	from central.billing.payments import mandates

	entry = instrument_catalogue.get(instrument) if instrument else None
	if entry and not entry["recurring"]:
		frappe.throw(
			_("{0} is a one-time payment — there is nothing to save.").format(entry["label"]),
			frappe.ValidationError,
		)
	gw = (
		gateway
		or (instrument and instrument_catalogue.gateway_for(instrument, currency))
		or _add_method_gateway(currency).get("name")
	)
	if entry and entry["method_type"] == "Card":
		return mandates.setup_card(
			team, gw, contact=contact, fallback_reason=entry["fallback_reason"]
		)
	if method_type == "Card" and not entry:
		return mandates.setup_card(team, gw, contact=contact)
	return mandates.setup_mandate(team, gw)


@frappe.whitelist(methods=["POST"])
def confirm_payment_method_order(
	payment_method: str | None = None,
	razorpay_payment_id: str | None = None,
	razorpay_order_id: str | None = None,
	razorpay_signature: str | None = None,
	razorpay_token_id: str | None = None,
) -> dict:
	"""Confirm the Razorpay Checkout callback — verifies the signature, activates
	the mandate. Real gateway verification, not a stub."""
	team = frappe.db.get_value("Payment Method", payment_method, "team")
	_require_manage(team)
	from central.billing.payments import mandates

	method = mandates.confirm_mandate(
		payment_method,
		{
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_order_id": razorpay_order_id,
			"razorpay_signature": razorpay_signature,
			"razorpay_token_id": razorpay_token_id,
		},
	)
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
