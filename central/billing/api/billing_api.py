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
from central.billing.api.dashboard._shared import (
	_add_method_gateway,
	_require_billing_setup,
	_team_currency,
)


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
	# Server-side backstop: no money movement until the billing profile (esp. currency)
	# is complete — else _team_currency falls back to INR and routes to the wrong gateway.
	_require_billing_setup(team)
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


# ── Metered services (team-level: AI tokens, email, PDF, …) ──────────────────
# The in-app flow a consumer service drives (ADR 0013/0015): discover service plans,
# subscribe (a synthesized subject, no VM), read what the team runs, and report usage.
# The team is always the credential's — never a parameter — so a pilot reports only its
# own team's consumption.


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def list_service_plans(cluster: str | None = None) -> dict:
	"""Active team-level service plans (AI tokens, email, PDF, storage), priced for the
	team's currency on `cluster`. Each entry carries the billing shape, family modes,
	included allowance, and the resolved rate."""
	from central.billing.catalog.services import list_service_plans as _list

	team = _team()
	currency = _team_currency(team)
	return {"plans": _list(currency, cluster=cluster), "currency": currency}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def subscribe_service(plan: str, cluster: str | None = None) -> dict:
	"""Subscribe the team to a team-level metered service. Mints a synthesized subject
	(no VM) and opens the price-lock segment inline; idempotent per (team, plan, cluster).
	Returns the subject + locked handles."""
	from central.billing.catalog.subscriptions import provision_service_subscription

	team = _team()
	_require_billing_setup(team)
	return provision_service_subscription(team, plan, cluster=cluster)


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def get_service_subscription() -> dict:
	"""The team's active team-level service subscriptions: subject, plan, cluster, rate,
	family modes, included allowance, and the current period's reported usage."""
	from central.billing.catalog.services import team_service_subscriptions

	return {"services": team_service_subscriptions(_team())}


@frappe.whitelist(allow_guest=True, methods=["GET"])
@pilot_credential_auth
def check_service_allowance(service: str, cluster: str | None = None) -> dict:
	"""Allowance state for edge enforcement, by the service the caller *is*: `{allowance,
	used, remaining, blocked, settlement_mode}`. A Prepaid Pack service polls this and
	degrades when `blocked`; a Postpaid Overage service never blocks. Central resolves the
	team's subject from `service` (the metered Resource Type) — the caller handles no
	subject. `exists: False` when the team isn't subscribed to it."""
	from central.billing.catalog.services import resolve_service_subject, service_allowance

	team = _team()
	subject = resolve_service_subject(team, service, cluster=cluster)
	if not subject:
		return {"exists": False}
	return service_allowance(team, subject)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def report_usage(
	service: str,
	quantity: float,
	cluster: str | None = None,
	sequence: int = 0,
	period: str | None = None,
) -> dict:
	"""Report metered usage for a team-level service — the minimal call a consumer service
	makes. It names the `service` it is (the metered Resource Type) and the `quantity`;
	Central derives everything else from the credential:

	  - the **team** (from the credential — a caller can only ever report its own team's
	    usage, so there is no subject to forge),
	  - the **subject** (resolved from team + service + cluster),
	  - the billing **period** (the current month unless `period="YYYY-MM"` backfills one),
	  - the **idempotency key** (subject + service + period).

	Authoritative families send the period's running total (replaced); Incremental families
	send a delta and bump `sequence` each flush (accumulated, retries/duplicates deduped).
	Returns `{recorded, service_subject}`; `recorded` is False if the team isn't subscribed
	to the service or it has no open billing segment."""
	from central.billing.catalog.services import resolve_service_subject
	from central.billing.catalog.subscriptions import active_segment_for_resource
	from central.billing.revenue.metering import ingest_rollup

	team = _team()
	subject = resolve_service_subject(team, service, cluster=cluster)
	if not subject:
		frappe.throw(
			frappe._("Team is not subscribed to service {0}.").format(service), frappe.ValidationError
		)

	# Stamp the subject's authoritative billing context (team + its real cluster +
	# currency) into the payload. A Live-priced family reads team/cluster/currency
	# straight from the meter (a grandfathered one re-derives them off the segment), so
	# without these a Live rollup would land context-less and be missed at invoicing.
	seg = active_segment_for_resource(subject)
	period_start, period_end, tag = _billing_period(period)
	key = ingest_rollup(
		{
			"resource_id": subject,
			"team": seg.team if seg else team,
			"cluster": seg.cluster if seg else cluster,
			"currency": seg.currency if seg else None,
			"resource_type": service,
			"meter_type": "Counter",
			"quantity": frappe.utils.flt(quantity),
			"period_start": period_start,
			"period_end": period_end,
			"idempotency_key": f"{subject}|{service}|{tag}",
			"sequence": frappe.utils.cint(sequence),
		}
	)
	return {"recorded": bool(key), "service_subject": subject}


def _billing_period(period: str | None) -> tuple[str, str, str]:
	"""The (start, end, tag) of a billing month. Defaults to the current month; `period`
	backfills a past one as `"YYYY-MM"`. The tag keys the rollup so all of a month's
	reports land on one row."""
	anchor = f"{period}-01" if period else frappe.utils.nowdate()
	first = frappe.utils.get_first_day(anchor)
	return str(first), str(frappe.utils.get_last_day(anchor)), first.strftime("%Y-%m")


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
# from the gateway, so no pending record is stored. A top-up credit is keyed on the
# underlying gateway payment id (the same id the capture webhook uses), so polling
# and the webhook backstop dedupe to a single credit.


@frappe.whitelist(allow_guest=True, methods=["POST"])
@pilot_credential_auth
def create_topup_checkout(amount: float, redirect_url: str) -> dict:
	"""Start a wallet top-up via hosted checkout. Returns `{checkout_url, reference,
	gateway}`; redirect the payer to `checkout_url`, then poll `get_checkout_status`."""
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	team = _team()
	# Same backstop as top-ups in the dashboard: require a complete profile (currency)
	# before money moves, so the wallet can't be locked to the INR fallback currency.
	_require_billing_setup(team)
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
	paid, amount, currency, payment_id = _read_session(gw_doc.adapter_key, session)

	if not paid:
		return {"status": "pending", "success": False, "message": "Awaiting payment."}

	if purpose == "topup":
		from central.billing.revenue import credits

		# Key on the UNDERLYING payment id (Stripe pi_/Razorpay pay_), the same id the
		# capture webhook credits on — so poll and webhook dedupe to a single credit.
		# (Falls back to the session id only if the gateway hasn't surfaced one yet.)
		key = payment_id or session_id
		credits.purchase(target, amount, currency, gateway_payment_id=key,
						 reference_name=key, note=f"Wallet top-up ({key})")
		return {"status": "paid", "success": True, "message": "Wallet topped up.",
				"balance": credits.get_balance(target)["balance"]}

	return {"status": "paid", "success": True, "message": "Payment received; invoice settling.",
			"invoice": target, "invoice_status": frappe.db.get_value("Invoice", target, "status")}


def _read_session(adapter_key: str, session: dict) -> tuple:
	"""Normalise a gateway checkout object to `(paid, amount_major, currency, payment_id)`.

	`payment_id` is the UNDERLYING payment — Stripe's PaymentIntent (`pi_…`), Razorpay's
	captured payment (`pay_…`) — not the session/link id. It is the same id the capture
	webhook credits on, so keying the poll credit on it makes poll and webhook dedupe."""
	if adapter_key == "Razorpay":
		paid = session.get("status") == "paid"
		minor = session.get("amount_paid") or session.get("amount") or 0
		payments = session.get("payments") or []
		captured = next((p for p in payments if p.get("status") == "captured"), None)
		payment_id = (captured or (payments[0] if payments else {})).get("payment_id")
	else:  # Stripe Checkout Session
		paid = session.get("payment_status") == "paid"
		minor = session.get("amount_total") or 0
		payment_id = session.get("payment_intent")
	return paid, frappe.utils.flt(minor) / 100.0, (session.get("currency") or "").upper(), payment_id
