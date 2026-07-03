# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""In-app billing API — a single facade of pilot-authenticated caller methods for a
site/pilot to drive a team's billing.

Every method authenticates via `pilot_credential_auth` (the X-Pilot-Token header → a
Pilot Credential bound to a team) and takes the **team from that credential**, never
a request parameter — so a pilot can only ever act on its own team (IDOR defence).
Record-scoped methods additionally check the record belongs to that team. No business
logic lives here; each method delegates to the existing billing service layer.
"""

import frappe

from central.api.pilot import pilot_credential_auth
from central.billing.api.dashboard._shared import _add_method_gateway, _team_currency


def _team() -> str:
	"""The team the authenticated pilot credential is bound to (never a request param)."""
	return frappe.local.pilot_credential.team


def _assert_owns(team_of_record: str | None) -> None:
	"""Guard a record-scoped call: the record must belong to the credential's team."""
	if team_of_record != _team():
		frappe.throw("Not permitted for this team.", frappe.PermissionError)


# ── Payment methods ──────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def add_payment_method(method_type: str = "Card", contact: str | None = None) -> dict:
	"""Begin adding a payment method for the team, on the gateway that serves its
	billing currency: Stripe for USD/EUR (card SetupIntent), Razorpay for INR
	(recurring Card, or UPI Autopay). Real card details are collected client-side by
	the gateway SDK/Checkout — this returns the handles that flow completes, plus the
	pending Payment Method to confirm via `confirm_payment_method`.

	`contact` is the phone Razorpay requires for a recurring card when the team's
	billing profile has none.
	"""
	from central.billing.payments import mandates, payments

	team = _team()
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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
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

	method_row = frappe.db.get_value("Payment Method", payment_method, ["team", "gateway"], as_dict=True)
	_assert_owns(method_row.team if method_row else None)
	adapter_key = frappe.db.get_value("Payment Gateway", method_row.gateway, "adapter_key")

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


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_available_plans(asset: str) -> dict:
	"""Active plans the team can switch `asset` to — priced for the team's currency on
	the asset's cluster, admitted by the trust tier, and within remaining headroom.
	Grouped by sub-category. The asset's cluster is resolved here; the underlying plan
	menu keys on cluster."""
	from central.billing.api.dashboard.catalog import get_eligible_plans

	team = _team()
	cluster = frappe.db.get_value("Asset", asset, "cluster")
	# The delegated menu gates on the session user's capability; the pilot is a Guest
	# session, so act as operator — the team is fixed from the verified credential.
	frappe.set_user("Administrator")
	return get_eligible_plans(cluster=cluster, team=team)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def change_plan(asset: str, plan: str) -> dict:
	"""Switch the asset's server onto a preset `plan`: validates + re-locks the rate at
	the current rate card and queues the VM reshape (stop→resize→start). Resolves the
	subscription from (team, asset). Returns `{queued, resized}`."""
	from central.billing.api.dashboard.catalog import resize_server

	subscription = frappe.db.get_value("Subscription", {"team": _team(), "asset_id": asset}, "name")
	if not subscription:
		frappe.throw(f"No subscription for asset {asset} on this team.", frappe.ValidationError)
	# resize_server gates on the session user's capability; act as operator (team is
	# fixed by the subscription lookup above, which is already scoped to the credential).
	frappe.set_user("Administrator")
	return resize_server(subscription, plan=plan)


# ── Credits ──────────────────────────────────────────────────────────────────


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_credit_balance() -> dict:
	"""The team's current prepaid wallet balance: `{"balance", "currency"}`."""
	from central.billing.revenue import credits

	return credits.get_balance(_team())


# ── Billing profile / address ────────────────────────────────────────────────

# The profile fields a caller may set (currency + legal identity + billing address);
# GSTIN is validated by the Billing Profile controller on save.
_PROFILE_FIELDS = (
	"currency", "legal_name", "email", "phone", "gstin",
	"address_line1", "address_line2", "city", "state", "country", "pincode",
)


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_billing_profile() -> dict:
	"""The team's billing profile (stored fields plus derived setup state:
	complete / missing / currency_locked / supported_currencies)."""
	from central.billing.api.dashboard.account import get_billing_profile as _get

	team = _team()
	# The delegated read gates on the session user's capability; act as operator (team
	# is fixed from the verified credential).
	frappe.set_user("Administrator")
	return _get(team)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def save_billing_profile(**fields) -> dict:
	"""Create/update the team's billing identity + address. Only the profile fields
	are accepted; the GSTIN is validated in the controller on save."""
	from central.billing.payments import profile

	team = _team()
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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_topup_checkout(amount: float, redirect_url: str) -> dict:
	"""Start a wallet top-up via hosted checkout. Returns `{checkout_url, reference,
	gateway}`; redirect the payer to `checkout_url`, then poll `get_checkout_status`."""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	team = _team()
	currency = _team_currency(team)
	return _create_hosted_checkout(
		team, currency, amount, purpose="topup", target=team, redirect_url=redirect_url,
		notes={"team": team, "purpose": "wallet_topup"},
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_invoice_checkout(invoice: str, redirect_url: str) -> dict:
	"""Start an on-session payment of an open invoice via hosted checkout. Returns
	`{checkout_url, reference, gateway}`; the invoice settles to Paid on the gateway
	webhook (webhook-truth), which `get_checkout_status` reports."""
	inv = frappe.get_doc("Invoice", invoice)
	_assert_owns(inv.team)
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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def get_checkout_status(reference: str) -> dict:
	"""Poll a hosted checkout. Returns `{status, success, message, ...}`. On the first
	observed `paid`: a top-up credits the wallet idempotently and returns the new
	balance; an invoice reports success (it flips to Paid on the gateway webhook)."""
	from central.billing.gateways.registry import get_adapter

	gateway, session_id, purpose, target = reference.split("|", 3)
	# Ownership: a top-up's target is the team; an invoice's target is the invoice.
	if purpose == "topup":
		_assert_owns(target)
	else:
		_assert_owns(frappe.db.get_value("Invoice", target, "team"))

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
