# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""In-app billing API — a single facade of whitelisted caller methods for a site
to drive a team's billing.

Each method takes `team` (or a record that resolves to one) and delegates to the
existing billing service layer; no business logic lives here. Authentication is
intentionally skipped for now — the team is taken as a parameter and acted on
directly — so a proper site-token auth layer can wrap this later without changing
the methods.
"""

import frappe

from central.billing.api.dashboard._shared import _add_method_gateway, _team_currency


# ── Payment methods ──────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def add_payment_method(team: str, method_type: str = "Card", contact: str | None = None) -> dict:
	"""Begin adding a payment method for the team, on the gateway that serves its
	billing currency: Stripe for USD/EUR (card SetupIntent), Razorpay for INR
	(recurring Card, or UPI Autopay). Real card details are collected client-side by
	the gateway SDK/Checkout — this returns the handles that flow completes, plus the
	pending Payment Method to confirm via `confirm_payment_method`.

	`contact` is the phone Razorpay requires for a recurring card when the team's
	billing profile has none.
	"""
	from central.billing.payments import mandates, payments

	currency = _team_currency(team)
	gw = _add_method_gateway(currency)
	gateway = gw.get("name")
	if not gateway:
		frappe.throw(f"No payment gateway is configured for {currency}.", frappe.ValidationError)

	adapter_key = gw.get("adapter_key")
	if adapter_key == "Razorpay":
		if method_type == "UPI Autopay":
			handles = mandates.setup_mandate(team, gateway)
		else:
			handles = mandates.setup_card(team, gateway, contact=contact)
	else:
		handles = payments.initiate_payment_method_setup(team, gateway)

	return {**handles, "gateway": gateway, "adapter_key": adapter_key, "method_type": method_type}


@frappe.whitelist(methods=["POST"])
def confirm_payment_method(
	payment_method: str,
	gateway_method_id: str | None = None,
	display_label: str | None = None,
	expiry_month: int | None = None,
	expiry_year: int | None = None,
	razorpay_payment_id: str | None = None,
	razorpay_order_id: str | None = None,
	razorpay_signature: str | None = None,
	razorpay_token_id: str | None = None,
) -> dict:
	"""Finalize the payment method the gateway SDK/Checkout tokenised. Routes by the
	method's gateway: Stripe runs the card micro-charge validation; Razorpay verifies
	the Checkout callback signature and activates the mandate/token."""
	from central.billing.payments import mandates, payments

	gateway = frappe.db.get_value("Payment Method", payment_method, "gateway")
	adapter_key = frappe.db.get_value("Payment Gateway", gateway, "adapter_key") if gateway else None

	if adapter_key == "Razorpay":
		method = mandates.confirm_mandate(payment_method, {
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_order_id": razorpay_order_id,
			"razorpay_signature": razorpay_signature,
			"razorpay_token_id": razorpay_token_id,
		})
	else:
		method = payments.confirm_payment_method(
			payment_method, gateway_method_id=gateway_method_id, display_label=display_label,
			expiry_month=expiry_month, expiry_year=expiry_year,
		)

	return {"payment_method": method.name, "status": method.status}


# ── Plans ────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_available_plans(team: str, asset: str) -> dict:
	"""Active plans the team can switch `asset` to — priced for the team's currency on
	the asset's cluster, admitted by the trust tier, and within remaining headroom.
	Grouped by sub-category. The asset's cluster is resolved here; the underlying plan
	menu keys on cluster."""
	from central.billing.api.dashboard.catalog import get_eligible_plans

	cluster = frappe.db.get_value("Asset", asset, "cluster")
	return get_eligible_plans(cluster=cluster, team=team)


@frappe.whitelist(methods=["POST"])
def change_plan(team: str, asset: str, plan: str) -> dict:
	"""Switch the asset's server onto a preset `plan`: validates + re-locks the rate at
	the current rate card and queues the VM reshape (stop→resize→start). Resolves the
	subscription from (team, asset). Returns `{queued, resized}`."""
	from central.billing.api.dashboard.catalog import resize_server

	subscription = frappe.db.get_value("Subscription", {"team": team, "asset_id": asset}, "name")
	if not subscription:
		frappe.throw(f"No subscription for asset {asset} on this team.", frappe.ValidationError)
	return resize_server(subscription, plan=plan)


# ── Credits ──────────────────────────────────────────────────────────────────


@frappe.whitelist()
def get_credit_balance(team: str) -> dict:
	"""The team's current prepaid wallet balance: `{"balance", "currency"}`."""
	from central.billing.revenue import credits

	return credits.get_balance(team)


# ── Billing profile / address ────────────────────────────────────────────────

# The profile fields a caller may set (currency + legal identity + billing address);
# GSTIN is validated by the Billing Profile controller on save.
_PROFILE_FIELDS = (
	"currency", "legal_name", "email", "phone", "gstin",
	"address_line1", "address_line2", "city", "state", "country", "pincode",
)


@frappe.whitelist()
def get_billing_profile(team: str) -> dict:
	"""The team's billing profile (stored fields plus derived setup state:
	complete / missing / currency_locked / supported_currencies)."""
	from central.billing.api.dashboard.account import get_billing_profile as _get

	return _get(team)


@frappe.whitelist(methods=["POST"])
def save_billing_profile(team: str, **fields) -> dict:
	"""Create/update the team's billing identity + address. Only the profile fields
	are accepted; the GSTIN is validated in the controller on save."""
	from central.billing.payments import profile

	values = {k: v for k, v in fields.items() if k in _PROFILE_FIELDS}
	doc = profile.create_or_update_billing_profile(team, **values)
	return {"saved": True, "team": team, "currency": doc.currency, "gstin": doc.gstin}


# ── Checkout (hosted URL + poll for status) ──────────────────────────────────
# A hosted-checkout flow for both gateways: create a Stripe Checkout Session / a
# Razorpay Payment Link for an amount, hand back the URL to redirect to, then poll
# get_checkout_status until the gateway reports paid. Stateless — the reference
# carries everything needed and the authoritative amount/currency are read back
# from the gateway, so no pending record is stored. The checkout id is the
# idempotency key (one checkout = one credit), so polling is safe to repeat.


@frappe.whitelist(methods=["POST"])
def create_topup_checkout(team: str, amount: float, redirect_url: str) -> dict:
	"""Start a wallet top-up via hosted checkout. Returns `{checkout_url, reference,
	gateway}`; redirect the payer to `checkout_url`, then poll `get_checkout_status`."""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	currency = _team_currency(team)
	return _create_hosted_checkout(
		team, currency, amount, purpose="topup", target=team, redirect_url=redirect_url,
		notes={"team": team, "purpose": "wallet_topup"},
	)


@frappe.whitelist(methods=["POST"])
def create_invoice_checkout(invoice: str, redirect_url: str) -> dict:
	"""Start an on-session payment of an open invoice via hosted checkout. Returns
	`{checkout_url, reference, gateway}`; the invoice settles to Paid on the gateway
	webhook (webhook-truth), which `get_checkout_status` reports."""
	inv = frappe.get_doc("Invoice", invoice)
	if inv.status not in ("Open", "Overdue"):
		frappe.throw("Invoice is not open for payment.", frappe.ValidationError)
	amount = frappe.utils.flt(inv.expected_collection)
	if amount <= 0:
		frappe.throw("Nothing is due on this invoice.", frappe.ValidationError)
	return _create_hosted_checkout(
		inv.team, inv.currency, amount, purpose="invoice", target=invoice, redirect_url=redirect_url,
		notes={"team": inv.team, "invoice": invoice, "purpose": "invoice_payment"},
	)


def _create_hosted_checkout(team, currency, amount, purpose, target, redirect_url, notes) -> dict:
	"""Create a hosted Stripe Checkout Session / Razorpay Payment Link on the gateway
	that serves the currency, and return the URL + a reference to poll."""
	from central.billing.api.dashboard._shared import _gateway_for_currency
	from central.billing.gateways.registry import get_adapter
	from central.billing.payments.payments import ensure_gateway_customer

	gateway = _gateway_for_currency(currency)
	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	# Stripe binds the session to the team's reused customer; Razorpay links take none.
	customer = ensure_gateway_customer(team, gateway, adapter) if gw_doc.adapter_key == "Stripe" else None
	receipt = f"{purpose}-{target}-{frappe.generate_hash(length=8)}"
	session = adapter.create_checkout_session(
		amount, currency, receipt, success_url=redirect_url, cancel_url=redirect_url,
		notes=notes, customer=customer,
	)
	reference = f"{gateway}|{session['session_id']}|{purpose}|{target}"
	return {"checkout_url": session["checkout_url"], "reference": reference,
			"gateway": gateway, "adapter_key": gw_doc.adapter_key, "amount": amount, "currency": currency}


@frappe.whitelist()
def get_checkout_status(reference: str) -> dict:
	"""Poll a hosted checkout. Returns `{status, success, message, ...}`. On the first
	observed `paid`: a top-up credits the wallet idempotently and returns the new
	balance; an invoice reports success (it flips to Paid on the gateway webhook)."""
	from central.billing.gateways.registry import get_adapter

	gateway, session_id, purpose, target = reference.split("|", 3)
	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	session = adapter.get_checkout_session(session_id)
	paid, amount, currency = _read_session(gw_doc.adapter_key, session)

	if not paid:
		return {"status": "pending", "success": False, "message": "Awaiting payment."}

	if purpose == "topup":
		from central.billing.revenue import credits

		# The checkout id is the idempotency key: repeated polling books one credit.
		credits.purchase(target, amount, currency, gateway_payment_id=session_id,
						 reference_name=session_id, note=f"Wallet top-up ({session_id})")
		return {"status": "paid", "success": True, "message": "Wallet topped up.",
				"balance": credits.get_balance(target)["balance"]}

	return {"status": "paid", "success": True, "message": "Payment received; invoice settling.",
			"invoice": target, "invoice_status": frappe.db.get_value("Invoice", target, "status")}


def _read_session(adapter_key: str, session: dict) -> tuple:
	"""Normalise a gateway checkout object to `(paid, amount_major, currency)`."""
	if adapter_key == "Razorpay":
		paid = session.get("status") == "paid"
		minor = session.get("amount_paid") or session.get("amount") or 0
	else:  # Stripe Checkout Session
		paid = session.get("payment_status") == "paid"
		minor = session.get("amount_total") or 0
	return paid, frappe.utils.flt(minor) / 100.0, (session.get("currency") or "").upper()
