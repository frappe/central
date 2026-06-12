# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Invoice, forecast, credit-ledger reads + wallet top-up / settlement actions.

Top-ups credit the wallet only after the gateway confirms the money moved
(create_topup_order opens the gateway order; confirm_topup verifies it).
"""

import frappe

from central.billing import authz
from central.billing.revenue import credits, invoicing, metering
from central.billing.revenue.tax import resolve_tax
from central.billing.api.dashboard._shared import (
	_describe_line,
	_gateway_for_currency,
	_require_billing_setup,
	_require_manage,
	_require_view,
	_resolve_team,
	_team_clusters,
	_team_currency,
)


@frappe.whitelist()
def get_forecast(team: str | None = None) -> dict:
	"""Current-month forecast: projected month-end bill vs credit balance.

	Driven by the same engine billing uses — fixed accrual from the price-lock
	segments (active resources projected to month-end) plus metered overage from
	the running-total rollups.
	"""
	team = _resolve_team(team)
	today = frappe.utils.getdate()
	month_start = frappe.utils.get_first_day(today)
	month_end = frappe.utils.get_last_day(today)

	line_items = []
	for cluster in _team_clusters(team):
		line_items += invoicing.compute_line_items(team, cluster, month_start, month_end)
		line_items += metering.metered_line_items(team, cluster, month_start, month_end)

	subtotal = frappe.utils.flt(sum(li["amount"] for li in line_items), 2)
	tax = resolve_tax(team, subtotal)
	projected_total = frappe.utils.flt(subtotal + tax["output_tax_amount"], 2)
	credit_balance = frappe.utils.flt(credits.get_balance(team)["balance"])
	shortfall = max(0.0, frappe.utils.flt(projected_total - credit_balance, 2))
	currency = _team_currency(team)

	return {
		"period_start": str(month_start),
		"period_end": str(month_end),
		"projected_total": projected_total,
		"subtotal": subtotal,
		"tax_amount": tax["output_tax_amount"],
		"tax_type": tax["output_tax_type"],
		"credit_balance": credit_balance,
		"shortfall": shortfall,
		"days_remaining": (month_end - today).days,
		"currency": currency,
		# Warn when the projected bill outruns the wallet (a top-up may be due).
		"credit_alert": shortfall > 0,
		# Spell out each service/plan + metered overage driving the projection.
		"line_items": [_describe_line(team, frappe._dict(li)) for li in line_items],
	}


@frappe.whitelist()
def list_subscriptions(team: str | None = None) -> list[dict]:
	team = _resolve_team(team)
	return frappe.get_all(
		"Subscription",
		filters={"team": team},
		fields=["name", "plan", "cluster", "billing_cycle", "account_standing", "start_date"],
		order_by="creation desc",
	)


@frappe.whitelist()
def list_invoices(team: str | None = None) -> list[dict]:
	"""Invoice history — summary only (no internal/admin fields)."""
	team = _resolve_team(team)
	return frappe.get_all(
		"Invoice",
		filters={"team": team},
		fields=["name", "period_start", "period_end", "status", "invoice_type",
				"total", "amount_paid", "currency", "due_date"],
		order_by="period_start desc",
	)


@frappe.whitelist()
def get_invoice(name: str) -> dict:
	"""One invoice with line items + tax block, scoped to the caller's team."""
	team = frappe.db.get_value("Invoice", name, "team")
	_require_view(team)
	doc = frappe.get_doc("Invoice", name)
	return {
		"name": doc.name, "team": doc.team, "status": doc.status, "invoice_type": doc.invoice_type,
		"period_start": str(doc.period_start), "period_end": str(doc.period_end),
		"currency": doc.currency, "subtotal": doc.subtotal,
		"output_tax_type": doc.output_tax_type, "output_tax_amount": doc.output_tax_amount,
		"zero_rating_reason": doc.zero_rating_reason, "total": doc.total,
		"credit_applied": doc.credit_applied, "expected_collection": doc.expected_collection,
		"amount_paid": doc.amount_paid, "due_date": str(doc.due_date) if doc.due_date else None,
		"items": [_describe_line(doc.team, li) for li in doc.items],
		"activity": _invoice_activity(doc),
	}


_PAYMENT_TITLES = {
	"Captured": "Card payment captured",
	"Failed": "Card payment failed",
	"Initiated": "Card payment initiated",
	"Authorised": "Card payment authorised",
	"Refunded": "Payment refunded",
}


def _invoice_activity(doc) -> list[dict]:
	"""Full lifecycle of one invoice as a timeline: finalised → credits applied →
	card attempts (incl. failed retries) → settled. This is the per-invoice
	payment history shown inside the invoice (no separate tab)."""
	events = [{
		"at": str(doc.creation),
		"kind": "issued",
		"title": "Invoice finalised",
		"detail": f"{doc.invoice_type} · {doc.period_start} → {doc.period_end}",
		"amount": frappe.utils.flt(doc.total),
		"currency": doc.currency,
		"theme": "gray",
	}]

	for e in frappe.get_all(
		"Credit Ledger Entry",
		filters={"reference_type": "Invoice", "reference_name": doc.name, "entry_type": "Debit"},
		fields=["amount", "currency", "created_at", "creation", "note"],
		order_by="creation asc",
	):
		events.append({
			"at": str(e.created_at or e.creation),
			"kind": "credit",
			"title": "Credits applied",
			"detail": "Drawn from wallet balance",
			"amount": frappe.utils.flt(e.amount),
			"currency": e.currency,
			"theme": "blue",
		})

	for p in frappe.get_all(
		"Payment Attempt",
		filters={"invoice": doc.name},
		fields=["status", "amount", "currency", "gateway", "gateway_transaction_id",
				"failure_code", "failure_reason", "retry_number",
				"initiated_at", "completed_at", "creation"],
		order_by="creation asc",
	):
		failed = p.status == "Failed"
		detail = p.failure_reason if failed else (
			f"Txn {p.gateway_transaction_id}" if p.gateway_transaction_id else p.gateway
		)
		if p.retry_number:
			detail = f"{detail or ''} · retry #{p.retry_number}".strip(" ·")
		events.append({
			"at": str(p.completed_at or p.initiated_at or p.creation),
			"kind": "payment",
			"title": _PAYMENT_TITLES.get(p.status, f"Card payment {str(p.status).lower()}"),
			"detail": detail,
			"amount": frappe.utils.flt(p.amount),
			"currency": p.currency,
			"theme": "green" if p.status == "Captured" else ("red" if failed else "orange"),
		})

	events.sort(key=lambda x: x["at"])

	# Closure marker, pinned to the last real event so it always reads last.
	if doc.status == "Paid":
		events.append({
			"at": events[-1]["at"] if events else str(doc.creation),
			"kind": "paid",
			"title": "Invoice settled",
			"detail": None,
			"amount": frappe.utils.flt(doc.total),
			"currency": doc.currency,
			"theme": "green",
		})

	for e in events:
		e["at"] = _fmt_when(e["at"])
	return events


def _fmt_when(dt) -> str | None:
	if not dt:
		return None
	try:
		return frappe.utils.get_datetime(dt).strftime("%d %b %Y, %H:%M")
	except Exception:
		return str(dt)


@frappe.whitelist()
def list_payment_attempts(team: str | None = None, limit: int = 100) -> list[dict]:
	"""Payment attempt history — every charge against the team's card/mandate,
	including the failed dunning retries that lead to suspension. This is the
	customer's record of WHY a card-on-file team can still be past_due/suspended.
	"""
	team = _resolve_team(team)
	return frappe.get_all(
		"Payment Attempt",
		filters={"team": team},
		fields=["name", "status", "amount", "currency", "gateway", "invoice",
				"failure_code", "failure_reason", "retry_number",
				"gateway_transaction_id", "creation"],
		order_by="creation desc",
		limit=limit,
	)


@frappe.whitelist()
def get_credit_balance(team: str | None = None) -> dict:
	team = _resolve_team(team)
	return {"balance": frappe.utils.flt(credits.get_balance(team)["balance"]), "currency": _team_currency(team)}


@frappe.whitelist()
def credit_ledger(team: str | None = None, limit: int = 50) -> list[dict]:
	team = _resolve_team(team)
	return frappe.get_all(
		"Credit Ledger Entry",
		filters={"team": team},
		fields=["entry_type", "amount", "running_balance", "currency", "note", "created_at",
				"reference_type", "reference_name"],
		order_by="creation desc",
		limit=limit,
	)


@frappe.whitelist(methods=["POST"])
def purchase_credits(team: str | None = None, amount: float | None = None,
					 payment_method: str | None = None) -> dict:
	"""Top up the prepaid wallet. (The card charge that funds it is the payment
	flow's concern; this books the resulting advance-liability credit.)"""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	return credits.purchase(team, amount, _team_currency(team),
							payment_method=payment_method, note="Wallet top-up")


@frappe.whitelist(methods=["POST"])
def pay_invoice(invoice: str | None = None) -> dict:
	"""Postpaid one-off settlement of an outstanding invoice (team-scoped)."""
	team = frappe.db.get_value("Invoice", invoice, "team")
	_require_manage(team)
	from central.billing.payments import charges

	return charges.pay_invoice(invoice)


@frappe.whitelist(methods=["POST"])
def create_topup_order(team: str | None = None, amount: float | None = None,
					   gateway: str | None = None) -> dict:
	"""Start a wallet top-up by creating a real gateway order. The UI opens the
	gateway's checkout against it; the wallet is credited only after the gateway
	confirms (verify in confirm_topup) — never magically."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	currency = _team_currency(team)
	gw = gateway or _gateway_for_currency(currency)
	from central.billing.gateways.registry import get_adapter

	gw_doc = frappe.get_doc("Payment Gateway", gw)
	adapter = get_adapter(gw_doc)
	receipt = f"topup-{team}-{frappe.generate_hash(length=8)}"
	notes = {"team": team, "purpose": "wallet_topup"}
	if gw_doc.adapter_key == "Stripe":
		# Hosted Stripe Checkout: the SPA redirects out and returns to /billing/credits,
		# which confirms the session. Stripe fills in {CHECKOUT_SESSION_ID}.
		from urllib.parse import quote

		base = frappe.utils.get_url()
		success_url = (f"{base}/billing/credits?topup=success&gateway={quote(gw)}"
					   f"&team={quote(team)}&session={{CHECKOUT_SESSION_ID}}")
		cancel_url = f"{base}/billing/credits?topup=cancelled"
		handles = adapter.create_checkout_session(amount, currency, receipt, success_url, cancel_url, notes=notes)
	else:
		handles = adapter.create_order(amount, currency, receipt, notes=notes)
	return {"gateway": gw, "adapter_key": gw_doc.adapter_key,
			"amount": amount, "currency": currency, "receipt": receipt, **handles}


@frappe.whitelist(methods=["POST"])
def confirm_topup(team: str | None = None, amount: float | None = None, gateway: str | None = None,
				  razorpay_order_id: str | None = None, razorpay_payment_id: str | None = None,
				  razorpay_signature: str | None = None, session: str | None = None) -> dict:
	"""Credit the wallet only after the gateway confirms the money really moved.
	Razorpay confirms via the checkout-callback signature; Stripe confirms by
	retrieving the hosted Checkout session and checking it was paid (and credits
	the server-confirmed amount, not a client-supplied one). The wallet is credited
	in the team's own currency — never assumed INR."""
	team = _resolve_team(team, authz.MANAGE)
	currency = _team_currency(team)
	amount = frappe.utils.flt(amount)
	from central.billing.gateways.registry import get_adapter

	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	if gw_doc.adapter_key == "Razorpay":
		ok = adapter.verify_payment_signature({
			"razorpay_order_id": razorpay_order_id,
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_signature": razorpay_signature,
		})
		reference = razorpay_payment_id
	else:
		# Hosted-checkout gateways (Stripe): trust the session the gateway confirms,
		# including the amount/currency it actually charged.
		checkout = adapter.get_checkout_session(session)
		ok = checkout.get("payment_status") == "paid"
		reference = checkout.get("payment_intent")
		if checkout.get("amount_total"):
			amount = frappe.utils.flt(checkout["amount_total"]) / 100
		if checkout.get("currency"):
			currency = checkout["currency"].upper()
	if not ok:
		frappe.throw("Payment confirmation failed.", frappe.ValidationError)
	return credits.purchase(team, amount, currency,
		reference_name=reference, note=f"Wallet top-up ({reference})",
		gateway_payment_id=reference)
