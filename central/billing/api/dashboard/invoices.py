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
	_enabled_gateway_for_currency,
	_gateway_for_currency,
	_paypal_gateway_for_currency,
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
	"""Active per-server subscriptions, enriched for display: the server's friendly
	name, its plan title, a human region label, and the resolved monthly price — the
	fields the dashboard renders instead of the raw hashes."""
	team = _resolve_team(team)
	from central.billing.regions import region_label

	rows = frappe.get_all(
		"Subscription",
		filters={"team": team},
		fields=["name", "plan", "pricing_mode", "sub_category", "cluster", "asset_id",
				"billing_cycle", "account_standing", "start_date", "enabled"],
		order_by="creation desc",
	)
	currency = _team_currency(team)
	# Batch the asset lookup so a team with N subscriptions costs one query, not N.
	asset_ids = list({r.asset_id for r in rows if r.asset_id})
	assets = (
		{
			a.name: a
			for a in frappe.get_all(
				"Asset",
				filters={"name": ["in", asset_ids]},
				fields=["name", "title", "gateway_url", "status"],
			)
		}
		if asset_ids
		else {}
	)
	# A composed config carries no Plan: its price is the locked rate of its open
	# billing segment (ADR 0010), and its "plan title" is a spec line built from the
	# composition. Batch both so a team with N composed configs stays O(1) queries.
	composed = [r.name for r in rows if r.pricing_mode == "Composed"]
	includes_by_sub = _composed_includes(composed)
	segment_rate = _open_segment_rates(team) if composed else {}

	plan_titles: dict[str, str] = {}
	rate_cache: dict[tuple, float | None] = {}
	out = []
	for r in rows:
		asset = assets.get(r.asset_id) or frappe._dict()
		if r.pricing_mode == "Composed":
			plan_title = _composed_label(r.sub_category, includes_by_sub.get(r.name, []))
			monthly_rate = segment_rate.get(r.name)
		else:
			if r.plan and r.plan not in plan_titles:
				plan_titles[r.plan] = frappe.db.get_value("Plan", r.plan, "title") or r.plan
			key = (r.plan, r.cluster)
			if r.plan and key not in rate_cache:
				rate_cache[key] = frappe.get_doc("Plan", r.plan).get_rate(currency, r.cluster)
			plan_title = plan_titles.get(r.plan)
			monthly_rate = rate_cache.get(key)
		out.append({
			"name": r.name,
			"server": asset.title or None,
			"gateway_url": asset.gateway_url or None,
			# The VM's operational state (Running/Stopped/Terminated/…) — the list shows
			# it distinctly from the billing-paused flag, and gates resume on it.
			"status": asset.status or None,
			"plan": r.plan,
			"plan_title": plan_title,
			"cluster": r.cluster,
			"region": region_label(r.cluster),
			"billing_cycle": r.billing_cycle,
			"account_standing": r.account_standing,
			"enabled": r.enabled,
			"monthly_rate": monthly_rate,
			"currency": currency,
		})
	return out


def _composed_includes(subscription_names: list[str]) -> dict[str, list]:
	"""The composition rows (qty per Resource Type) for each composed subscription, in
	one batched query — keyed by subscription name."""
	if not subscription_names:
		return {}
	by_sub: dict[str, list] = {}
	for row in frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Subscription", "parent": ["in", subscription_names]},
		fields=["parent", "resource_type", "quantity", "unit"],
	):
		by_sub.setdefault(row.parent, []).append(row)
	return by_sub


def _open_segment_rates(team: str) -> dict[str, float]:
	"""subscription -> its open segment's locked rate, the authoritative billed price
	(ADR 0010), for the team's subscriptions in one batched read."""
	from central.billing.catalog.subscriptions import team_active_segments

	return {s.subscription: s.locked_rate for s in team_active_segments(team)}


def _composed_label(sub_category: str | None, includes: list) -> str:
	"""A composed config's display title, mirroring a preset's 'Profile — specs' shape,
	e.g. 'General — 1 vCPU · 4 GB RAM · 40 GB disk'."""
	from central.billing.catalog.composition import config_summary

	summary = config_summary(includes)
	if sub_category and summary:
		return f"{sub_category} — {summary}"
	return summary or "Custom config"


@frappe.whitelist(methods=["POST"])
def pause_subscription(subscription: str, team: str | None = None) -> dict:
	"""Pause billing for a subscription (records intent + disables it, ADR 0006)."""
	owner = frappe.db.get_value("Subscription", subscription, "team")
	_require_manage(owner)
	from central.billing.catalog import subscriptions

	doc = subscriptions.pause_billing(subscription)
	return {"name": doc.name, "enabled": doc.enabled}


@frappe.whitelist(methods=["POST"])
def resume_subscription(subscription: str, team: str | None = None) -> dict:
	"""Resume billing for a paused subscription."""
	owner = frappe.db.get_value("Subscription", subscription, "team")
	_require_manage(owner)
	from central.billing.catalog import subscriptions

	doc = subscriptions.resume_billing(subscription)
	return {"name": doc.name, "enabled": doc.enabled}


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
	from central.billing.payments.charges import _IN_FLIGHT

	# An attempt already charging (or captured and awaiting the settlement webhook)
	# means the money is moving — the UI must show a "settling" state, not a Pay
	# button, so the customer can't fire a second charge (#10).
	payment_in_progress = bool(
		frappe.db.exists("Payment Attempt", {"invoice": name, "status": ["in", _IN_FLIGHT]})
	)
	return {
		"name": doc.name, "team": doc.team, "status": doc.status, "invoice_type": doc.invoice_type,
		"period_start": str(doc.period_start), "period_end": str(doc.period_end),
		"currency": doc.currency, "subtotal": doc.subtotal,
		"output_tax_type": doc.output_tax_type, "output_tax_rate": doc.output_tax_rate,
		"output_tax_amount": doc.output_tax_amount,
		"zero_rating_reason": doc.zero_rating_reason, "total": doc.total,
		"credit_applied": doc.credit_applied, "expected_collection": doc.expected_collection,
		"amount_paid": doc.amount_paid, "due_date": str(doc.due_date) if doc.due_date else None,
		"payment_in_progress": payment_in_progress,
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

	# Closure marker, pinned to the last real event so it stays the newest event —
	# the list is returned newest-first, so this reads at the top.
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
	events.reverse()  # newest first — the latest state reads at the top
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
def pay_invoice(invoice: str | None = None) -> dict:
	"""Postpaid one-off settlement of an outstanding invoice (team-scoped)."""
	team = frappe.db.get_value("Invoice", invoice, "team")
	_require_manage(team)
	from central.billing.payments import charges

	return charges.pay_invoice(invoice)


@frappe.whitelist(methods=["POST"])
def pay_invoice_checkout(invoice: str | None = None) -> dict:
	"""Open an on-session gateway checkout to pay an invoice yourself
	(collection_mode = manual_checkout). Any amount — on-session has no ₹15k limit."""
	team = frappe.db.get_value("Invoice", invoice, "team")
	_require_manage(team)
	from central.billing.payments import charges

	return charges.create_invoice_payment_order(invoice)


@frappe.whitelist(methods=["POST"])
def confirm_invoice_checkout(attempt: str | None = None, razorpay_order_id: str | None = None,
							 razorpay_payment_id: str | None = None,
							 razorpay_signature: str | None = None) -> dict:
	"""Verify the on-session checkout callback; the invoice settles on the webhook."""
	team = frappe.db.get_value("Payment Attempt", attempt, "team")
	_require_manage(team)
	from central.billing.payments import charges

	return charges.confirm_invoice_payment(
		attempt, razorpay_order_id=razorpay_order_id,
		razorpay_payment_id=razorpay_payment_id, razorpay_signature=razorpay_signature)


@frappe.whitelist(methods=["POST"])
def create_topup_order(team: str | None = None, amount: float | None = None,
					   gateway: str | None = None, method: str | None = None) -> dict:
	"""Start a wallet top-up by creating a real gateway order. The UI opens the
	gateway's checkout against it; the wallet is credited only after the gateway
	confirms (verify in confirm_topup) — never magically.

	`method="paypal"` routes an international top-up to the configured PayPal gateway
	(non-INR card default stays Stripe). That gateway's `paypal_settlement_mode` then
	picks the rail:
	  - Direct: PayPal's own merchant account; the SPA renders PayPal Buttons and the
	    capture id reconciles against PayPal's ledger (ADR 0007).
	  - Via Razorpay: PayPal is collected inside the Razorpay sheet and settles through
	    Razorpay (ADR 0005). The order is created on the currency's Razorpay gateway and
	    `display_paypal` tells the SPA to surface the PayPal block in that sheet; the
	    reference stored is the razorpay_payment_id."""
	team = _resolve_team(team, authz.MANAGE)
	_require_billing_setup(team)
	amount = frappe.utils.flt(amount)
	if amount <= 0:
		frappe.throw("Top-up amount must be greater than zero.", frappe.ValidationError)
	currency = _team_currency(team)
	display_paypal = False
	if method == "paypal":
		pp = frappe.get_doc("Payment Gateway", _paypal_gateway_for_currency(currency))
		if pp.is_paypal_via_razorpay():
			gw = _enabled_gateway_for_currency(currency, "Razorpay")
			if not gw:
				frappe.throw(
					f"PayPal via Razorpay needs an enabled Razorpay gateway that handles {currency}.",
					frappe.ValidationError,
				)
			display_paypal = True
		else:
			gw = pp.name
	else:
		gw = gateway or _gateway_for_currency(currency)
	from central.billing.gateways.registry import get_adapter

	gw_doc = frappe.get_doc("Payment Gateway", gw)
	adapter = get_adapter(gw_doc)
	# Mint-or-reuse the team's customer at this gateway *before* the order, so the
	# top-up attaches to the one customer every later charge reuses (the card #05 and
	# mandate #08 paths share this same Gateway Customer row). ensure_gateway_customer
	# commits the row the instant it mints, so a failed order can't orphan it.
	from central.billing.payments.payments import ensure_gateway_customer

	customer_id = ensure_gateway_customer(team, gw, adapter)
	receipt = f"topup-{team}-{frappe.generate_hash(length=8)}"
	notes = {"team": team, "purpose": "wallet_topup"}
	# Both rails collect the card in-app: Razorpay in its hosted sheet over the
	# returned order, Stripe via a PaymentIntent the SPA confirms with Stripe.js
	# (no hosted-Checkout redirect). The India-export billing address rides on the
	# Stripe PaymentIntent from the Billing Profile, so it's never re-asked.
	handles = adapter.create_order(amount, currency, receipt, notes=notes, customer=customer_id)
	# The SPA branches on adapter_key: Stripe → PaymentIntent Element, Razorpay → hosted
	# sheet, Paypal → PayPal Buttons against the returned order_id (ADR 0007). For a
	# Via-Razorpay PayPal top-up the adapter_key is Razorpay (settlement runs there) and
	# display_paypal asks the sheet to surface the PayPal block.
	return {"gateway": gw, "adapter_key": gw_doc.adapter_key, "display_paypal": display_paypal,
			"amount": amount, "currency": currency, "receipt": receipt, **handles}


@frappe.whitelist(methods=["POST"])
def confirm_topup(team: str | None = None, amount: float | None = None, gateway: str | None = None,
				  razorpay_order_id: str | None = None, razorpay_payment_id: str | None = None,
				  razorpay_signature: str | None = None, payment_intent: str | None = None,
				  paypal_order_id: str | None = None) -> dict:
	"""Credit the wallet only after the gateway confirms the money really moved.
	Razorpay confirms via the checkout-callback signature; Stripe by retrieving the
	PaymentIntent the SPA charged; PayPal by capturing the approved order. Each
	credits the server-confirmed amount/currency (never a client-supplied figure)
	and records the gateway's own reference — for PayPal the capture id, which
	settles directly and so reconciles against PayPal's ledger (#21, ADR 0007). The
	wallet is credited in the team's own currency. Idempotent on the gateway payment
	id, so a capture webhook crediting in parallel is a no-op."""
	team = _resolve_team(team, authz.MANAGE)
	currency = _team_currency(team)
	amount = frappe.utils.flt(amount)
	from central.billing.gateways.registry import get_adapter

	gw_doc = frappe.get_doc("Payment Gateway", gateway)
	adapter = get_adapter(gw_doc)
	if gw_doc.adapter_key == "Razorpay":
		# The callback signature binds order_id|payment_id, NOT the amount — so the
		# request figure can't be trusted. Fetch the payment server-side and credit
		# what Razorpay actually captured, mirroring the Stripe/PayPal branches.
		ok = adapter.verify_payment_signature({
			"razorpay_order_id": razorpay_order_id,
			"razorpay_payment_id": razorpay_payment_id,
			"razorpay_signature": razorpay_signature,
		})
		reference = razorpay_payment_id
		if ok:
			payment = adapter.get_payment(razorpay_payment_id)
			ok = payment.get("status") == "captured"
			minor = payment.get("amount")
			if minor is None:
				# A captured payment always carries an amount; a response without
				# one must not fall through to the client-supplied figure.
				frappe.throw("Razorpay reported no amount for this payment.", frappe.ValidationError)
			amount = frappe.utils.flt(minor) / 100
			if payment.get("currency"):
				currency = payment["currency"].upper()
	elif gw_doc.adapter_key == "Paypal":
		# Capture the order the buyer approved in PayPal Buttons; credit what PayPal
		# actually took (major units already) and key the wallet entry on the capture id.
		capture = adapter.capture_order(paypal_order_id)
		ok = capture.get("status") == "COMPLETED"
		reference = capture.get("id")
		if capture.get("amount") is None:
			frappe.throw("PayPal reported no amount for this capture.", frappe.ValidationError)
		amount = frappe.utils.flt(capture["amount"])
		if capture.get("currency"):
			currency = capture["currency"].upper()
	else:
		# In-app PaymentIntent (Stripe): the SPA confirmed the card with Stripe.js;
		# trust the intent the gateway reports, including the amount/currency it
		# actually charged — never a client-supplied figure.
		intent = adapter.get_payment_intent(payment_intent)
		ok = intent.get("status") == "succeeded"
		reference = intent.get("id")
		minor = intent.get("amount_received") or intent.get("amount")
		if minor is None:
			frappe.throw("Stripe reported no amount for this payment intent.", frappe.ValidationError)
		amount = frappe.utils.flt(minor) / 100
		if intent.get("currency"):
			currency = intent["currency"].upper()
	if not ok:
		frappe.throw("Payment confirmation failed.", frappe.ValidationError)
	return credits.purchase(team, amount, currency,
		reference_name=reference, note=f"Wallet top-up ({reference})",
		gateway_payment_id=reference)
