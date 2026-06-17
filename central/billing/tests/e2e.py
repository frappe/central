# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Test-only seed/teardown endpoints for the Playwright e2e suite (no mocks).

Each spec calls `seed(scenario=...)` to get a *fully isolated* team + user (with a
known password) so it can drive the real dashboard against the real backend and
the real gateway test sandboxes — Stripe/Razorpay test keys already live in
`common_site_config.json`, so a top-up creates a genuine test-mode PaymentIntent /
Razorpay order, nothing stubbed.

Safety: these are whitelisted but HARD-GATED on `frappe.conf.allow_tests`. On a
site without that flag (i.e. production) every entry point raises immediately, so
the seed/teardown surface can never be reached off a test bench.
"""

import frappe
from frappe.utils.password import update_password

from central.iam import get_user_team_names
from central.billing.tests.utils import complete_billing_profile, make_user

# Shared login secret for every seeded user — the spec gets it back from seed() and
# logs in with it. Not a real credential; only valid on an allow_tests bench.
E2E_PASSWORD = "e2e-Test-Pass-123"


def _enter_test_mode() -> None:
	"""Gate, then elevate. These endpoints are called by an unauthenticated test
	harness (allow_guest) and must create/delete teams and users across permission
	hooks, so they run as Administrator. The ONLY thing that makes that safe is the
	`allow_tests` gate — it is never set on a production site, so this whole surface
	is unreachable there. Checked first, before any elevation."""
	if not frappe.conf.get("allow_tests"):
		frappe.throw("e2e seed endpoints require `allow_tests` on the site.", frappe.PermissionError)
	frappe.set_user("Administrator")


# --- public entry points -----------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def seed(scenario: str = "profile_pending", currency: str = "INR") -> dict:
	"""Build an isolated team for one Playwright spec and return the handles the
	test needs: the team slug, and the member's login (email + password).

	Scenarios (each builds on the previous):
	  - `profile_pending` — team + billing member, NO billing profile. Lands the
	    user on the onboarding wizard; the spec completes the profile itself.
	  - `ready`           — `profile_pending` + a *complete* billing profile in
	    `currency`, so money-moving actions (top-up, add card) are un-gated.
	  - `with_invoices`   — `ready` + one Paid and one Open invoice, for the
	    invoices screen.

	Pass `currency="USD"` for the Stripe top-up spec: USD's default gateway is
	Stripe, so the top-up deterministically routes to the Stripe card Element.

	The seeded user owns exactly one team — the personal team Central bootstraps on
	user creation (`central.users.bootstrap_user_team`), where they are Owner with
	full billing capability. We seed onto *that* team so it is the deterministic
	whoami default; the spec never has to switch teams.
	"""
	_enter_test_mode()

	member = make_user(f"e2e-{frappe.generate_hash(8)}@example.com")
	update_password(member, E2E_PASSWORD)
	team = get_user_team_names(member)[0]

	if scenario in ("ready", "with_invoices"):
		complete_billing_profile(team, currency=currency)
	if scenario == "with_invoices":
		_seed_invoices(team, currency)

	frappe.db.commit()
	return {"team": team, "email": member, "password": E2E_PASSWORD, "currency": currency, "scenario": scenario}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def teardown(team: str | None = None, email: str | None = None) -> dict:
	"""Delete everything `seed()` created for one spec. Best-effort and idempotent:
	a spec calls this in its afterEach, so it must never raise on partially-built
	state. Billing rows go first (they link the team), then the team, then the user
	(who is the team's owner). `email` is also deleted directly in case the team was
	never created."""
	_enter_test_mode()

	if team and frappe.db.exists("Team", team):
		owner = frappe.db.get_value("Team", team, "owner_user")
		for dt in (
			"Invoice", "Payment Attempt", "Subscription", "Payment Method",
			"Credit Ledger Entry", "Gateway Customer", "Billing Profile",
			"Trust Tier", "Tax Profile",
		):
			frappe.db.delete(dt, {"team": team})
		frappe.db.delete("Credit Wallet", {"team": team})
		frappe.delete_doc("Team", team, force=True, ignore_permissions=True)
		_delete_user(owner)

	_delete_user(email)
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def finish_razorpay_topup(team: str, gateway: str, order_id: str, amount: float) -> dict:
	"""Complete a Razorpay top-up the way the hosted-checkout callback would — but
	without driving Razorpay's bot-protected sheet (hCaptcha/fraud frames/3DS) which
	can't be automated reliably.

	The e2e spec drives the real UI up to the point where the genuine Razorpay test
	sheet opens against a *real* test order (proving the UI → create_topup_order
	integration). This then finishes the no-mock path the gateway boundary leaves:
	it computes the **real** checkout signature with the **real** test secret over
	that **real** order (exactly the HMAC Razorpay's callback returns), mints a
	payment id, and calls the **real** `confirm_topup` — which verifies the signature
	with the test key and credits the wallet. The only synthetic value is the
	`pay_…` id string, because minting a Razorpay-issued one needs its hosted sheet.
	"""
	import hashlib
	import hmac

	_enter_test_mode()
	from central.billing.api.dashboard.invoices import confirm_topup
	from central.billing.gateways.registry import get_adapter

	adapter = get_adapter(frappe.get_doc("Payment Gateway", gateway))
	secret = adapter.get_credential("api_secret")
	payment_id = f"pay_e2e{frappe.generate_hash(length=14)}"
	signature = hmac.new(
		secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
	).hexdigest()

	return confirm_topup(
		team=team, amount=amount, gateway=gateway,
		razorpay_order_id=order_id, razorpay_payment_id=payment_id, razorpay_signature=signature,
	)


# --- settlement helpers (invoice charge + credits waterfall) -----------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
def add_credits(team: str, amount: float, currency: str | None = None) -> dict:
	"""Fund the team's wallet through the real credit ledger (credits.purchase) —
	the same append-only Credit Ledger Entry a confirmed top-up books. Lets a
	settlement spec arrange a known balance without driving a gateway top-up."""
	_enter_test_mode()
	from central.billing.revenue import credits

	currency = currency or frappe.db.get_value("Billing Profile", team, "currency") or "USD"
	credits.purchase(team, frappe.utils.flt(amount), currency, note="e2e wallet funding")
	frappe.db.commit()
	return {"team": team, "balance": credits.get_balance(team)["balance"]}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def save_test_card(team: str) -> dict:
	"""Attach a **real** Stripe test card to the team so invoice charges hit the real
	off-session PaymentIntent path (no mock). Builds a PaymentMethod from `tok_visa`
	on the team's real gateway customer, then records the active Payment Method the
	collection loop charges. Card teams are USD (USD's default gateway is Stripe)."""
	_enter_test_mode()
	import stripe

	from central.billing.gateways.registry import get_adapter, resolve_gateway_for_currency
	from central.billing.payments.payments import densify_priorities, ensure_gateway_customer

	currency = frappe.db.get_value("Billing Profile", team, "currency") or "USD"
	gateway = resolve_gateway_for_currency(currency)
	adapter = get_adapter(frappe.get_doc("Payment Gateway", gateway))
	customer_id = ensure_gateway_customer(team, gateway, adapter)

	stripe.api_key = adapter.get_credential("api_secret")
	pm = stripe.PaymentMethod.create(type="card", card={"token": "tok_visa"})
	stripe.PaymentMethod.attach(pm.id, customer=customer_id)

	name = frappe.get_doc({
		"doctype": "Payment Method", "team": team, "gateway": gateway, "method_type": "Card",
		"status": "Active", "display_label": "Visa ····4242", "is_default": 1,
		"gateway_method_id": pm.id, "gateway_customer_id": customer_id,
		"expiry_month": 12, "expiry_year": 2034, "validated_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True).name
	densify_priorities(team)
	frappe.db.commit()
	return {"payment_method": name, "gateway": gateway, "gateway_method_id": pm.id}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def make_invoice(team: str, total: float = 1180, currency: str | None = None,
				 link_card: int = 0) -> dict:
	"""Create a Draft Billable invoice (subtotal + tax = total) the waterfall can
	open and collect. Returns its name.

	With `link_card`, attach a minimal Subscription whose `default_payment_method`
	is the team's active card — real invoices always come from a subscription, and
	the manual 'Pay' button (`pay_invoice`) resolves the method through it."""
	_enter_test_mode()
	currency = currency or frappe.db.get_value("Billing Profile", team, "currency") or "USD"
	total = frappe.utils.flt(total)
	tax = frappe.utils.flt(total - total / 1.18, 2)  # treat total as tax-inclusive at 18%
	subtotal = frappe.utils.flt(total - tax, 2)

	subscription = None
	if int(link_card):
		card = frappe.db.get_value(
			"Payment Method", {"team": team, "status": "Active"}, ["name", "gateway"], as_dict=True
		)
		if card:
			subscription = frappe.get_doc({
				"doctype": "Subscription", "team": team, "status": "Active",
				"default_payment_method": card.name, "gateway": card.gateway,
			}).insert(ignore_permissions=True).name

	name = frappe.get_doc({
		"doctype": "Invoice", "team": team, "invoice_type": "Billable", "status": "Draft",
		"subscription": subscription,
		"period_start": "2026-06-01", "period_end": "2026-06-30", "currency": currency,
		"subtotal": subtotal, "output_tax_type": "GST" if currency == "INR" else "VAT",
		"output_tax_amount": tax, "total": total, "tds_amount": 0, "expected_collection": total,
		"items": [{"resource_type": "bundle", "rate": subtotal, "days": 30, "amount": subtotal}],
	}).insert(ignore_permissions=True).name
	frappe.db.commit()
	return {"invoice": name, "total": total, "currency": currency, "subscription": subscription}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def settle(team: str, invoice: str, collect: int = 1) -> dict:
	"""Run the real credits-then-card waterfall (open_and_collect): apply wallet
	credits, then — if `collect` — charge the remainder to the team's card via the
	real off-session PaymentIntent. With `collect=0` the invoice is opened (credits
	applied) but left for the UI 'Pay' button to charge. Returns the waterfall
	result, plus the in-flight attempt name so the spec can deliver its webhook."""
	_enter_test_mode()
	from central.billing.revenue.invoicing.lifecycle import open_and_collect

	result = open_and_collect(invoice, collect=bool(int(collect)))
	attempt = frappe.db.get_value(
		"Payment Attempt", {"invoice": invoice, "status": "Captured"}, "name"
	)
	frappe.db.commit()
	return {**result, "attempt": attempt}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def deliver_webhook(attempt: str) -> dict:
	"""Deliver the gateway success webhook for a captured attempt — the only path
	that flips an Open invoice to Paid (charges.apply_webhook → _settle_invoice).

	Stripe/Razorpay webhooks can't reach a local bench, so we build the Webhook
	Event from the attempt's **real** captured transaction id and run the **real**
	apply_webhook. Only the HTTP signature check (a separate security gate covered
	by unit tests) is skipped; the settlement logic and the txn id are real."""
	_enter_test_mode()
	from central.billing.payments import charges

	att = frappe.get_doc("Payment Attempt", attempt)
	adapter_key = frappe.db.get_value("Payment Gateway", att.gateway, "adapter_key")
	if adapter_key == "Stripe":
		event_type = "payment_intent.succeeded"
		payload = {"id": f"evt_e2e{frappe.generate_hash(10)}", "type": event_type,
				   "data": {"object": {"id": att.gateway_transaction_id}}}
	else:
		event_type = "payment.captured"
		payload = {"event": event_type,
				   "payload": {"payment": {"entity": {"id": att.gateway_transaction_id}}}}

	event = frappe.get_doc({
		"doctype": "Webhook Event", "gateway": att.gateway, "event_type": event_type,
		"gateway_event_id": payload.get("id") or frappe.generate_hash(12),
		"status": "Received", "raw_payload": frappe.as_json(payload),
	}).insert(ignore_permissions=True)
	result = charges.apply_webhook(event.name)
	frappe.db.commit()
	return result


# --- scenario builders -------------------------------------------------------


def _seed_invoices(team: str, currency: str) -> None:
	"""One settled and one outstanding invoice — enough to exercise the list (a
	Paid + an Open row) and the detail view (line items + a tax block)."""
	tax_type = "GST" if currency == "INR" else "VAT"
	for status, period, paid in (
		("Paid", ("2026-05-01", "2026-05-31"), True),
		("Open", ("2026-06-01", "2026-06-30"), False),
	):
		frappe.get_doc({
			"doctype": "Invoice", "team": team, "invoice_type": "Billable", "status": status,
			"period_start": period[0], "period_end": period[1], "currency": currency,
			"subtotal": 1000, "output_tax_type": tax_type, "output_tax_amount": 180, "total": 1180,
			"amount_paid": 1180 if paid else 0,
			"items": [{"resource_type": "bundle", "rate": 1000, "days": 30, "amount": 1000}],
		}).insert(ignore_permissions=True)


# --- helpers -----------------------------------------------------------------


def _delete_user(email: str | None) -> None:
	if email and frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
