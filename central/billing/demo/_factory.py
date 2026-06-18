# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Demo data shape + record builders for the billing seed (see demo_scenarios).

The catalog constants (clusters, plan sizes, tiers, gateways) and the idempotent
`_upsert`-based builders that turn them into Plans / Trust Tier Levels / Payment
Gateways / per-team config. The orchestration that wires teams together lives in
demo_scenarios.
"""

import frappe

from central.billing.catalog.pricing import set_catalog_rates

# --- catalog shape ----------------------------------------------------------

# (slug, label, billing currency of the region)
CLUSTERS = [
	("in-mumbai", "India — Mumbai", "INR"),
	("eu-frankfurt", "Europe — Frankfurt", "EUR"),
	("me-dubai", "Middle East — Dubai", "USD"),
]
CURRENCIES = ["INR", "EUR", "USD"]
# 1 unit of currency = N INR (rough FX, demo only).
FX = {"INR": 1.0, "EUR": 90.0, "USD": 83.0}
# Regional cost multiplier on the INR base price.
CLUSTER_MULT = {"in-mumbai": 1.0, "eu-frankfurt": 1.25, "me-dubai": 1.15}

# (slug, title, vcpu, ram_gb, disk_gb, transfer_gb_included, base_inr_monthly)
PLAN_SIZES = [
	("plan-1vcpu", "Starter · 1 vCPU / 2 GB", 1, 2, 25, 100, 1500),
	("plan-2vcpu", "Basic · 2 vCPU / 4 GB", 2, 4, 50, 200, 3000),
	("plan-4vcpu", "Standard · 4 vCPU / 8 GB", 4, 8, 100, 400, 6000),
	("plan-8vcpu", "Pro · 8 vCPU / 16 GB", 8, 16, 200, 800, 12000),
	("plan-16vcpu", "Enterprise · 16 vCPU / 32 GB", 16, 32, 400, 1600, 24000),
]

# Metered bandwidth overage, priced per GB per currency (cluster-agnostic).
ADDON = "addon-transfer"
ADDON_RATE = {"INR": 0.80, "EUR": 0.009, "USD": 0.010}

# (level, sequence, is_default, max_spend_inr, max_resources, min_invoices, min_paid_inr)
TIERS = [
	("t0", 0, 1, 5000, 3, 0, 0),
	("t1", 1, 0, 50000, 25, 1, 3000),
	("t2", 2, 0, 200000, 100, 6, 50000),
	("t3", 3, 0, 1000000, 500, 10, 500000),
]

# Output tax follows the customer's billing currency (place of supply).
TAX_BY_CURRENCY = {"INR": ("GST", 18), "EUR": ("VAT", 19), "USD": ("VAT", 5)}

STRIPE = {"INR": "GW-Stripe-INR", "EUR": "GW-Stripe-EUR", "USD": "GW-Stripe-USD"}
RAZORPAY = "GW-Razorpay"
# PayPal is a directly-settled standalone gateway (ADR 0007). It lists USD/EUR but
# is NOT their default — Stripe stays the card default; PayPal is the opt-in rail.
PAYPAL = "GW-PayPal"
ANCHOR = "2026-06-01"  # the current (open) billing month


# --- catalog / config builders ----------------------------------------------


def _tiers():
	for level, seq, default, cap, res, inv, paid in TIERS:
		# The TIERS table is denominated in INR; the per-currency thresholds are
		# derived from it at seed time via FX (a one-off seeding convenience — the
		# runtime never converts, it reads the row for the team's currency).
		thresholds = [
			{
				"currency": c,
				"max_spend": round(cap / FX[c], 2),
				"min_cumulative_paid": round(paid / FX[c], 2),
			}
			for c in CURRENCIES
		]
		_upsert("Trust Tier Level", level, {
			"tier": level, "sequence": seq, "is_default": default,
			"max_resource_count": res, "min_paid_invoices": inv,
			"thresholds": thresholds,
		}, newname=True)


def _catalog():
	for slug, title, vcpu, ram, disk, transfer, base_inr in PLAN_SIZES:
		rates = []
		for cslug, _label, _cur in CLUSTERS:
			for currency in CURRENCIES:
				rate = round(base_inr * CLUSTER_MULT[cslug] / FX[currency], 2)
				rates.append({"cluster": cslug, "currency": currency, "rate": rate})
		plan = _upsert("Plan", slug, {
			"title": title, "billing_cycle": "Monthly", "is_active": 1,
			"includes": [
				{"resource_type": "Compute", "quantity": vcpu, "unit": "vCPU"},
				{"resource_type": "Memory", "quantity": ram, "unit": "GB"},
				{"resource_type": "Disk", "quantity": disk, "unit": "GB"},
				{"resource_type": "Transfer", "quantity": transfer, "unit": "GB"},
			],
		}, newname=True)
		set_catalog_rates("Plan", plan, rates)

	addon = _upsert("Add-on", ADDON, {
		"title": "Bandwidth Overage", "resource_type": "Transfer", "unit": "GB",
		"billing_type": "Metered", "billing_interval": "Monthly",
	}, newname=True)
	set_catalog_rates(
		"Add-on", addon, [{"cluster": "", "currency": c, "rate": ADDON_RATE[c]} for c in CURRENCIES]
	)


def _gateways():
	# Demo keys are placeholders — skip live credential validation / webhook
	# auto-registration so the seed runs offline.
	seed = {"skip_credential_validation": True}
	for currency, name in STRIPE.items():
		_upsert("Payment Gateway", name, {
			"title": f"Stripe ({currency})", "adapter_key": "Stripe",
			"api_secret": "sk_test_demo", "webhook_secret": "whsec_demo", "is_enabled": 1,
			"currencies": [{"currency": currency, "is_default": 1}],
		}, newname=True, flags=seed)
	_upsert("Payment Gateway", RAZORPAY, {
		"title": "Razorpay (India)", "adapter_key": "Razorpay",
		"api_key": "rzp_test", "api_secret": "rzp_secret", "webhook_secret": "rzp_whsec",
		"is_enabled": 1, "supports_mandates": 1,
		"currencies": [{"currency": "INR", "is_default": 1}],
	}, newname=True, flags=seed)
	# PayPal — directly-settled standalone gateway (ADR 0007). Non-default for USD/EUR
	# so Stripe stays their card default; PayPal is the opt-in international rail whose
	# capture ids reconcile against PayPal's own ledger.
	_upsert("Payment Gateway", PAYPAL, {
		"title": "PayPal (International)", "adapter_key": "Paypal",
		"api_key": "paypal_client_id", "api_secret": "paypal_secret", "webhook_secret": "paypal_whid",
		"is_enabled": 1,
		"currencies": [{"currency": "USD", "is_default": 0}, {"currency": "EUR", "is_default": 0}],
	}, newname=True, flags=seed)


def _tier(team, level):
	# The tier is a link on the Billing Profile; the cap resolves live from the
	# level × the team's currency. manual_override pins the demo team's tier.
	frappe.db.set_value("Billing Profile", team, {
		"trust_tier_level": level, "trust_tier": level, "manual_override": 1,
	})


def _tax(team, currency):
	tax_type, rate = TAX_BY_CURRENCY[currency]
	_upsert("Tax Profile", team, {"team": team, "output_tax_type": tax_type, "output_tax_rate": rate})


# country must be a valid Country (Billing Profile.country is a Link); for India
# the state must be a GST state whose code matches the GSTIN (27 = Maharashtra).
_GEO_BY_CLUSTER = {
	"in-mumbai": ("India", "Maharashtra", "Mumbai", "400001"),
	"eu-frankfurt": ("Germany", "Hesse", "Frankfurt", "60311"),
	"me-dubai": ("United Arab Emirates", "Dubai", "Dubai", "00000"),
}


def _profile(team, slug, currency, cluster):
	india = currency == "INR"
	country, state, city, pincode = _GEO_BY_CLUSTER.get(cluster, ("India", "Maharashtra", "Mumbai", "400001"))
	_upsert("Billing Profile", team, {
		"team": team, "currency": currency,
		"legal_name": f"{slug.replace('-', ' ').title()} Ltd",
		"email": f"billing@{slug}.example",
		"gstin": "27AAPFU0939F1ZV" if india else None,
		"address_line1": "1 Demo Street", "city": city,
		"state": state, "country": country, "pincode": pincode,
	})


# --- team roster (members + custom role) ------------------------------------

# (suffix, system role, member status) — a roster with role AND status variety so
# the Members & Roles screen shows the full spread. Roster users are created
# DISABLED so User.after_insert never bootstraps a personal team for them; they
# exist only as members of the demo team.
_MEMBER_ROSTER = [
	("admin", "Admin", "Active"),
	("dev", "Developer", "Active"),
	("billing", "Billing", "Active"),
	("viewer", "Viewer", "Active"),
	("contractor", "Developer", "Suspended"),
	("invitee", "Viewer", "Invited"),
]

# One team-scoped CUSTOM role, to exercise the custom-role path end to end: read
# billing and operate (start/stop) VMs, but not manage members or terminate.
_CUSTOM_ROLE = ("Finance & Ops", ["billing:view", "billing:manage", "vm:view", "vm:start", "vm:stop"])


def _team_members(team, slug):
	"""Give the demo team a realistic roster — members on varied system roles with
	status variety, plus one team-scoped custom role. Idempotent: resets the roster
	(and the team's custom role) on every reseed, keeping only the Owner."""
	role = _custom_role(team)
	doc = frappe.get_doc("Team", team)
	doc.members = [m for m in doc.members if m.user == doc.owner_user]
	for suffix, member_role, status in _MEMBER_ROSTER + [("finance", role, "Active")]:
		email = f"{suffix}-{slug}@example.com"
		_ensure_member_user(email, f"{suffix.title()} ({slug})")
		doc.append("members", {"user": email, "role": member_role, "status": status})
	doc.save(ignore_permissions=True)


def _custom_role(team):
	"""(Re)create this team's single custom Team Role and return its name."""
	for existing in frappe.get_all("Team Role", {"team": team, "is_system": 0}, pluck="name"):
		frappe.delete_doc("Team Role", existing, force=True, ignore_permissions=True)
	name, caps = _CUSTOM_ROLE
	return frappe.get_doc({
		"doctype": "Team Role", "role_name": name, "is_system": 0, "team": team,
		"capabilities": [{"capability": c} for c in caps],
	}).insert(ignore_permissions=True).name


def _ensure_member_user(email, full_name):
	"""Roster-only user, created DISABLED so the after_insert hook doesn't bootstrap
	a personal team (central.users.bootstrap_user_team skips disabled users)."""
	if frappe.db.exists("User", email):
		return email
	first, _, last = full_name.partition(" ")
	frappe.get_doc({
		"doctype": "User", "email": email, "first_name": first, "last_name": last or None,
		"send_welcome_email": 0, "enabled": 0,
	}).insert(ignore_permissions=True)
	return email


def _payment_setup(team, slug, currency, state):
	"""Return (gateway, payment_method) for the team's terminal state."""
	if state in ("credits", "credits_full", "free_credits", "trial"):
		return None, None  # settled from wallet / free credits — no card needed
	if currency == "INR" and slug == "wayne-ent":
		# An INR team on UPI Autopay (mandate ceiling = tier cap).
		pm = frappe.get_doc({
			"doctype": "Payment Method", "team": team, "gateway": RAZORPAY,
			"method_type": "UPI Autopay", "status": "Active", "display_label": "UPI Autopay",
			"gateway_method_id": f"token_{slug}", "gateway_customer_id": f"cust_{slug}",
			"mandate_max_amount": 200000, "mandate_currency": "INR", "is_default": 1,
			"validated_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True).name
		_gateway_customer(team, RAZORPAY, f"cust_{slug}")
		return RAZORPAY, pm
	gateway = STRIPE[currency]
	pm = frappe.get_doc({
		"doctype": "Payment Method", "team": team, "gateway": gateway, "method_type": "Card",
		"status": "Active", "display_label": "Visa ····4242", "gateway_method_id": f"pm_{slug}",
		"gateway_customer_id": f"cus_{slug}", "expiry_month": 11, "expiry_year": 2030,
		"is_default": 1, "validated_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True).name
	_gateway_customer(team, gateway, f"cus_{slug}")
	return gateway, pm


def _gateway_customer(team, gateway, customer_id):
	"""Mirror the production Gateway Customer store: one (team, gateway)→customer_id
	row, the id every payment-method setup, recurring charge AND wallet top-up reuses.
	The demo Payment Methods carry the same id, so the store stays consistent — the
	state the v10 backfill leaves."""
	existing = frappe.db.get_value("Gateway Customer", {"team": team, "gateway": gateway}, "name")
	if existing:
		frappe.delete_doc("Gateway Customer", existing, force=True)
	frappe.get_doc({
		"doctype": "Gateway Customer", "team": team, "gateway": gateway,
		"adapter_key": frappe.db.get_value("Payment Gateway", gateway, "adapter_key"),
		"gateway_customer_id": customer_id,
	}).insert(ignore_permissions=True)


def _failed_attempt(team, invoice, pm, gateway, retry, when=None):
	when = when or frappe.utils.now_datetime()
	frappe.get_doc({
		"doctype": "Payment Attempt", "invoice": invoice, "team": team, "gateway": gateway,
		"payment_method": pm, "amount": frappe.db.get_value("Invoice", invoice, "expected_collection"),
		"currency": frappe.db.get_value("Invoice", invoice, "currency"), "status": "Failed",
		"failure_code": "card_declined", "failure_reason": "Your card was declined.",
		"retry_number": retry, "initiated_at": when, "completed_at": when,
	}).insert(ignore_permissions=True)


def _settle_with_retries(team, invoice, pm, gateway, retries, amount, currency):
	"""Dunning-then-settle trail on a paid invoice: `retries` failed card attempts
	(declined), each a day apart from the invoice's period end, followed by a
	successful capture that settles it. This is what the invoice Activity shows."""
	period_end = frappe.db.get_value("Invoice", invoice, "period_end")
	base = frappe.utils.get_datetime(f"{period_end} 09:00:00")
	for n in range(retries):
		_failed_attempt(team, invoice, pm, gateway, n, when=frappe.utils.add_to_date(base, days=n))
	captured_at = frappe.utils.add_to_date(base, days=retries)
	frappe.get_doc({
		"doctype": "Payment Attempt", "invoice": invoice, "team": team, "gateway": gateway,
		"payment_method": pm, "amount": amount, "currency": currency, "status": "Captured",
		"retry_number": retries, "gateway_transaction_id": f"pi_{invoice}",
		"resolved_by": "Webhook", "initiated_at": captured_at, "completed_at": captured_at,
	}).insert(ignore_permissions=True)
	frappe.db.set_value("Invoice", invoice, {
		"status": "Paid", "amount_paid": amount,
		"due_date": frappe.utils.add_days(period_end, 7),
	})


# --- collection mode (ADR 0005, #50) ----------------------------------------


def set_collection_mode(team, mode):
	"""Set how this team's invoices are collected (drives the dashboard banner)."""
	frappe.db.set_value("Billing Profile", team, "collection_mode", mode)


def arm_emandate(team):
	"""Run the real e-mandate flow on the team's open invoice: trip Action Required
	if it's over the ₹15,000 silent ceiling, else send the pre-debit notice. Using
	the live logic means the banner shows true numbers and a genuine notification."""
	from central.billing.payments import collection_mode, emandate

	open_inv = frappe.db.get_value(
		"Invoice", {"team": team, "status": "Open"}, ["name", "expected_collection"], as_dict=True
	)
	if not open_inv:
		return
	st = collection_mode.evaluate(
		team, projected_amount=frappe.utils.flt(open_inv.expected_collection),
		reason="invoice_over_threshold",
	)
	if not st["action_required"]:
		emandate.schedule_predebit(open_inv.name)


# --- helpers ----------------------------------------------------------------


def _month_periods(n):
	"""The n closed month windows immediately before ANCHOR, oldest first."""
	anchor = frappe.utils.getdate(ANCHOR)
	out = []
	for i in range(n, 0, -1):
		start = frappe.utils.add_months(anchor, -i)
		out.append((str(start), str(frappe.utils.get_last_day(start))))
	return out


def _upsert(doctype, name, values, newname=False, flags=None):
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=True)
	data = {"doctype": doctype, **values}
	if newname:
		data["__newname"] = name
	doc = frappe.get_doc(data)
	if flags:
		doc.flags.update(flags)
	return doc.insert(ignore_permissions=True).name


def _ensure_signing_key():
	if frappe.conf.get("entitlement_private_key"):
		return
	from central.billing.catalog.signing import generate_keypair

	priv, pub = generate_keypair()
	frappe.conf.entitlement_private_key = priv
	try:
		frappe.installer.update_site_config("entitlement_private_key", priv)
		frappe.installer.update_site_config("entitlement_public_key", pub)
	except Exception:  # noqa: BLE001 — in-memory conf is enough for the seed run
		pass


def _ensure_demo_team(slug):
	"""Resolve a demo slug to a real Central `Team`, ONE per owner.

	Creating the owner user fires `bootstrap_user_team` (User.after_insert),
	which already provisions that user's default Team *with* proper Owner
	membership. We reuse that team rather than minting a second, member-less one
	(which is what produced two teams per email). Idempotent by `owner_user`:
	`_wipe_all` leaves Teams intact, so a re-seed reuses the same team."""
	owner = f"owner-{slug}@example.com"
	existing = frappe.db.get_value("Team", {"owner_user": owner}, "name")
	if existing:
		return existing
	if not frappe.db.exists("User", owner):
		frappe.get_doc({
			"doctype": "User", "email": owner, "send_welcome_email": 0,
			"first_name": slug.replace("-", " ").title(),
		}).insert(ignore_permissions=True)
	# bootstrap_user_team should have created the team on user insert; fall back
	# to an explicit one only if bootstrap was skipped.
	team = frappe.db.get_value("Team", {"owner_user": owner}, "name")
	if team:
		return team
	return frappe.get_doc({
		"doctype": "Team", "team_name": slug, "owner_user": owner,
	}).insert(ignore_permissions=True).name


def _wipe_all():
	"""Drop every billing record so the demo is the only data present."""
	children = ("Catalog Rate", "Plan Includes", "Invoice Line Item",
				"Subscription Change")
	transactional = ("Invoice", "Payment Attempt", "Refund", "Payment Method", "Gateway Customer",
					 "Price Lock", "Usage Rollup", "Credit Ledger Entry", "Credit Wallet",
					 "Billing Notification Log", "Entitlement Token", "Webhook Event", "Subscription")
	config = ("Tax Profile", "Billing Profile")
	catalog = ("Plan", "Add-on", "Payment Gateway", "Trust Tier Level")
	for dt in children + transactional + config + catalog:
		try:
			frappe.db.delete(dt)
		except Exception:  # noqa: BLE001 — some doctypes may not exist on older sites
			pass
	frappe.db.commit()
