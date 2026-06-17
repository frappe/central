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
			"Invoice", "Payment Attempt", "Payment Method", "Credit Ledger Entry",
			"Gateway Customer", "Billing Profile", "Trust Tier", "Tax Profile",
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
