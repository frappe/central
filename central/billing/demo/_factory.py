# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Demo data shape + record builders for the billing seed (see demo_scenarios).

The catalog constants (clusters, plan sizes, tiers, gateways) and the idempotent
`_upsert`-based builders that turn them into Plans / Trust Tier Levels / Payment
Gateways / per-team config. The orchestration that wires teams together lives in
demo_scenarios.
"""

import frappe
from frappe.utils.password import update_password

# --- catalog shape ----------------------------------------------------------

# (slug, label, billing currency of the region)
CLUSTERS = [
	("in-mumbai", "India — Mumbai", "INR"),
	("me-dubai", "Middle East — Dubai", "USD"),
]
CURRENCIES = ["INR", "USD"]
# 1 unit of currency = N INR (rough FX, demo only).
FX = {"INR": 1.0, "USD": 83.0}
# Regional cost multiplier on the INR base price.
CLUSTER_MULT = {"in-mumbai": 1.0, "me-dubai": 1.15}

# (slug, title, vcpu, ram_gb, disk_gb, transfer_gb_included, base_inr_monthly)
PLAN_SIZES = [
	("plan-1vcpu", "Starter · 1 vCPU / 2 GB", 1, 2, 25, 100, 1500),
	("plan-2vcpu", "Basic · 2 vCPU / 4 GB", 2, 4, 50, 200, 3000),
	("plan-4vcpu", "Standard · 4 vCPU / 8 GB", 4, 8, 100, 400, 6000),
	("plan-8vcpu", "Pro · 8 vCPU / 16 GB", 8, 16, 200, 800, 12000),
	("plan-16vcpu", "Enterprise · 16 vCPU / 32 GB", 16, 32, 400, 1600, 24000),
]

# À-la-carte component rate card, per Resource Type (ADR 0009) — what powers the
# "design your own" plan selector. A composed config prices as Σ(qty × component rate);
# a config is only sellable when EVERY component it uses is priced. Base per-unit/month
# in INR (Compute per vCPU, Memory/Disk per GB), converted per currency at seed time.
COMPONENT_RATES_INR = {"Compute": 1200.0, "Memory": 400.0, "Disk": 30.0}

# Team-level metered CONSUMER services (ADR 0013/0015) — the real metered story
# (replaces the meaningless bandwidth overage). Each is a single-resource metered Plan
# under its own family, billed as postpaid overage past a bundled allowance.
# Unit is a plain label ("Nos") and Quantity is the ACTUAL count — allowances are real
# item counts, and the rate is per item (a token costs a small fraction of a cent).
# (family/category, resource_type, plan_slug, title, unit, allowance, per-unit rate by currency)
# allowance is 0 — these services have NO free tier: every reported unit is billed at
# the per-unit rate (pure pay-per-use), so nothing is included for free.
SERVICES = [
	("AI Tokens", "Tokens", "svc-ai-tokens", "AI Tokens", "Nos", 0, {"INR": 0.012, "USD": 0.00015}),
	("Emails", "Emails", "svc-emails", "Transactional Email", "Nos", 0, {"INR": 0.007, "USD": 0.00009}),
	("PDF Generation", "PDF", "svc-pdf", "PDF / Print Generation", "Nos", 0, {"INR": 0.018, "USD": 0.00022}),
]

# (level, sequence, is_default, max_spend_inr, max_resources, min_invoices, min_paid_inr)
TIERS = [
	("t0", 0, 1, 5000, 3, 0, 0),
	("t1", 1, 0, 50000, 25, 1, 3000),
	("t2", 2, 0, 200000, 100, 6, 50000),
	("t3", 3, 0, 1000000, 500, 10, 500000),
]

# Output tax follows the customer's billing currency (place of supply).
TAX_BY_CURRENCY = {"INR": ("GST", 18), "USD": ("VAT", 5)}

STRIPE = {"INR": "GW-Stripe-INR", "USD": "GW-Stripe-USD"}
RAZORPAY = "GW-Razorpay"
# PayPal is a directly-settled standalone gateway (ADR 0007). It lists USD but
# is NOT its default — Stripe stays the card default; PayPal is the opt-in rail.
PAYPAL = "GW-PayPal"
ANCHOR = "2026-06-01"  # the current (open) billing month
DEMO_OWNER_PASSWORD = "abc@123"  # every demo owner logs into the console with this


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


def _atlas_instances():
	"""Each demo cluster needs a real Atlas Instance — Catalog Rate scopes its
	regional rates to one via a Link (autonamed by region)."""
	wanted = {cslug for cslug, _label, _cur in CLUSTERS}
	# Drop demo regions no longer offered (e.g. a retired EUR cluster) so a re-seed on
	# an existing site doesn't leave a stray instance behind. Scoped to demo-created
	# instances (the `*.atlas.demo` base_url) so a real Atlas is never touched.
	for stray in frappe.get_all(
		"Atlas Instance",
		filters={"region": ["not in", wanted], "base_url": ["like", "%.atlas.demo"]},
		pluck="name",
	):
		frappe.delete_doc("Atlas Instance", stray, force=True, ignore_permissions=True)
	for cslug, label, _cur in CLUSTERS:
		if frappe.db.exists("Atlas Instance", cslug):
			continue
		frappe.get_doc({
			"doctype": "Atlas Instance", "region": cslug,
			"base_url": f"https://{cslug}.atlas.demo", "api_key": "demo", "api_secret": "demo",
		}).insert(ignore_permissions=True)


# Logical plan key (PLAN_SIZES / SERVICES slug) -> the hash-named Plan the Plan
# Configurator minted for it. Plans are authored through the configurator, so their
# names are opaque hashes; the demo refers to them by these stable logical keys.
_PLAN_BY_KEY: dict[str, str] = {}


def plan_name(key: str) -> str:
	"""Resolve a demo logical plan key (e.g. 'plan-2vcpu', 'svc-ai-tokens') to the
	configurator-minted Plan name."""
	return _PLAN_BY_KEY[key]


def _catalog():
	from central.billing.catalog.taxonomy_setup import ensure_catalog_masters

	_atlas_instances()
	# Seed the taxonomy masters (Plan Category / Resource Type) through the canonical
	# seeder — the demo authors plans against these families, it does not invent them.
	ensure_catalog_masters()
	_PLAN_BY_KEY.clear()
	_vm_plans()
	_component_rate_card()
	_service_catalog()


def _vm_plans():
	"""Author the VM bundle ladder + its per-cluster prices through a real Plan
	Configurator DOCUMENT — the exact doc the Desk 'Launch a plan' verb creates —
	so the demo exercises the whole authoring flow (doc.generate_and_price), not just
	its internal helpers, and the configurator list isn't empty.

	The configurator prices `rate = base_rate(currency) × rung.multiplier`. We carry
	each size's base INR price as its `multiplier`, and the per-cluster×FX factor as
	the base_rate — so re-running generation per cluster (as an admin would when a
	region onboards) yields the regional prices. The Plans are minted on the first
	run and reused (idempotent) on the rest."""
	doc = frappe.get_doc({
		"doctype": "Plan Configurator",
		"template_name": "VM Bundles (demo)",
		"category": "VM Plans",
		"sub_category": "General",
		"start_vcpu": "1", "ceiling_vcpu": "16",
		"billing_cycle": "Monthly",
		"is_active": 1,
		"plan_name_prefix": "Bundle",
		"rungs": [
			{"plan_name": slug, "label": title, "vcpu": vcpu, "memory_gb": ram,
			 "disk_gb": disk, "transfer_gb": transfer, "multiplier": base}
			for slug, title, vcpu, ram, disk, transfer, base in PLAN_SIZES
		],
	}).insert(ignore_permissions=True)

	for cslug, _label, _cur in CLUSTERS:
		doc.set("base_rates", [
			{"currency": c, "base_rate": CLUSTER_MULT[cslug] / FX[c]} for c in CURRENCIES
		])
		doc.save(ignore_permissions=True)
		doc.generate_and_price(cluster=cslug, currencies=list(CURRENCIES))

	doc.reload()
	for rung, size in zip(doc.rungs, PLAN_SIZES):
		_PLAN_BY_KEY[size[0]] = rung.plan


def _component_rate_card():
	"""À-la-carte per-Resource-Type rates (ADR 0009/0011) authored through the Plan
	Configurator's component-rate card — the same 'Publish Rates' path the Desk tool
	uses — rather than writing Catalog Rate rows by hand. Global (blank-cluster) rate
	per currency for each priced component."""
	doc = frappe.get_doc({
		"doctype": "Plan Configurator",
		"template_name": "Component Rate Card (demo)",
		"category": "VM Plans",
		"start_vcpu": "1", "ceiling_vcpu": "16",
		"component_rates": [
			{"resource_type": rt, "currency": c, "rate": round(base_inr / FX[c], 4)}
			for rt, base_inr in COMPONENT_RATES_INR.items()
			for c in CURRENCIES
		],
	}).insert(ignore_permissions=True)
	doc.apply_component_card(cluster=None)


def _service_catalog():
	"""Team-level metered consumer services (AI tokens, email, PDF) — each authored
	through a real Plan Configurator DOCUMENT on the `Simple` builder (one simple-plan
	row + a per-currency base rate), against the canonical service families seeded by
	ensure_catalog_masters. Single-resource metered Plan per family, per-unit priced,
	globally (ADR 0013/0015/0008)."""
	for category, resource_type, slug, title, unit, allowance, rates in SERVICES:
		doc = frappe.get_doc({
			"doctype": "Plan Configurator",
			"template_name": f"{title} (demo)",
			"category": category,
			"start_vcpu": "1", "ceiling_vcpu": "16",
			"billing_cycle": "Monthly",
			"is_active": 1,
			"simple_plans": [
				{"title": title, "resource_type": resource_type,
				 "quantity": allowance, "unit": unit, "multiplier": 1}
			],
			"base_rates": [{"currency": c, "base_rate": rate} for c, rate in rates.items()],
		}).insert(ignore_permissions=True)
		doc.generate_and_price(cluster=None, currencies=list(rates.keys()))
		doc.reload()
		_PLAN_BY_KEY[slug] = doc.simple_plans[0].plan


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
	# PayPal — directly-settled standalone gateway (ADR 0007). Non-default for USD
	# so Stripe stays the card default; PayPal is the opt-in international rail whose
	# capture ids reconcile against PayPal's own ledger.
	_upsert("Payment Gateway", PAYPAL, {
		"title": "PayPal (International)", "adapter_key": "Paypal",
		"api_key": "paypal_client_id", "api_secret": "paypal_secret", "webhook_secret": "paypal_whid",
		"is_enabled": 1,
		"currencies": [{"currency": "USD", "is_default": 0}],
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
# billing and operate servers, but not manage members or terminate.
_CUSTOM_ROLE = ("Finance & Ops", ["billing:view", "billing:manage", "server:view", "server:power"])


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


# States that settle from the wallet / free credits — no card on file.
_NO_CARD_STATES = ("credits", "credits_full", "free_credits", "trial")
# INR teams on UPI Autopay (Razorpay e-mandate); the ceiling = the tier cap.
_MANDATE_TEAMS = ("acme-corp",)


def _payment_setup(team, slug, currency, state):
	"""Return (gateway, payment_method) for the team's terminal state."""
	if state in _NO_CARD_STATES:
		return None, None  # settled from wallet / free credits — no card needed
	if currency == "INR" and slug in _MANDATE_TEAMS:
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


def _add_backup_card(team, slug, gateway, priority=1):
	"""A second, lower-priority Card on the same gateway customer — the backup method
	autopay rotates to when the primary declines (#28). The primary from `_payment_setup`
	carries priority 0, so this one (priority 1) sits behind it in `ordered_methods`."""
	return frappe.get_doc({
		"doctype": "Payment Method", "team": team, "gateway": gateway, "method_type": "Card",
		"status": "Active", "display_label": "Mastercard ····5454",
		"gateway_method_id": f"pm_{slug}_backup", "gateway_customer_id": f"cus_{slug}",
		"expiry_month": 8, "expiry_year": 2031, "is_default": 0, "priority": priority,
		"validated_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True).name


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


def _settle_via_backup(team, invoice, primary_pm, gateway, amount, currency, when=None):
	"""Autopay fallback (#28): the primary method declines, so settlement rotates to the
	team's backup method, which captures. The rotation target is chosen by the REAL
	selector (collection.next_method_for) — the demo only stands in for the offline
	gateway capture. Returns (backup_attempt, backup_pm) or (None, None) if there is no
	backup to fall back to. Leaves the invoice Paid on the backup capture."""
	from central.billing.payments import collection

	when = frappe.utils.get_datetime(when or frappe.utils.now_datetime())
	# 1) the primary declines (the Failed row is what the selector reads to skip it).
	_failed_attempt(team, invoice, primary_pm, gateway, 0, when=when)
	# 2) the real fallback selector picks the next untried, chargeable method.
	backup = collection.next_method_for(invoice, team)
	if not backup:
		return None, None
	# 3) the backup captures (stands in for the offline gateway), an hour later.
	captured_at = frappe.utils.add_to_date(when, hours=1)
	attempt = _capture_attempt(team, invoice, backup.name, backup.gateway, amount, currency, when=captured_at)
	frappe.db.set_value("Invoice", invoice, {"status": "Paid", "amount_paid": amount})
	return attempt, backup.name


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
	doc = frappe.get_doc({"doctype": doctype, **values})
	if newname:
		# Plan (and other catalog masters) autoname by random hash, so `__newname` is
		# ignored — pin the readable slug the same way the Team seed does, so Links
		# like Subscription.plan / Catalog Rate.priced_for resolve to it.
		doc.flags.name_set = True
		doc.name = name
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
	if not frappe.db.exists("User", owner):
		frappe.get_doc({
			"doctype": "User", "email": owner, "send_welcome_email": 0,
			"first_name": slug.replace("-", " ").title(),
		}).insert(ignore_permissions=True)
	# Every demo owner signs into the console with the same password. Set it on each
	# seed (owners persist across reseeds) via update_password, which writes the hash
	# directly and so bypasses the site's password-strength policy.
	update_password(owner, DEMO_OWNER_PASSWORD)
	existing = frappe.db.get_value("Team", {"owner_user": owner}, "name")
	if existing:
		return existing
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
	# Child tables must be wiped explicitly — deleting a parent via frappe.db.delete
	# does NOT cascade, so orphan rows (e.g. old EUR Trust Tier Thresholds, gateway
	# currencies) would otherwise accumulate across re-seeds.
	children = ("Catalog Rate", "Plan Includes", "Invoice Line Item",
				"Subscription Change", "Trust Tier Threshold", "Payment Gateway Currency",
				"Plan Configurator Plan", "Plan Configurator Rate",
				"Plan Configurator Simple Plan", "Plan Configurator Component Rate")
	transactional = ("Invoice", "Payment Attempt", "Refund", "Payment Method", "Gateway Customer",
					 "Usage Rollup", "Credit Ledger Entry", "Credit Wallet",
					 "Billing Notification Log", "Team Notification",
					 "Entitlement Token", "Webhook Event", "Subscription", "Asset")
	config = ("Tax Profile", "Billing Profile")
	catalog = ("Plan Configurator", "Plan", "Payment Gateway", "Trust Tier Level")
	for dt in children + transactional + config + catalog:
		try:
			frappe.db.delete(dt)
		except Exception:  # noqa: BLE001 — some doctypes may not exist on older sites
			pass
	frappe.db.commit()


# --- resize (Plan Changed) segments -----------------------------------------


def _plan_after(plan, steps=1):
	"""The plan `steps` sizes up (or down, if negative) the PLAN_SIZES ladder,
	clamped to the ends. Used to stage a realistic VM upsize/downsize."""
	order = [p[0] for p in PLAN_SIZES]
	i = order.index(plan) if plan in order else 0
	return order[max(0, min(len(order) - 1, i + steps))]


def _add_resize(sub, plan, currency, cluster, effective_at):
	"""Author one 'Plan Changed' run-segment on the ledger (ADR 0010 — the ledger is
	the price-lock). The invoice day-weights every segment, so back-to-back resizes in
	a single period show up as distinct slivers in the bill and the change history."""
	rate = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
	frappe.get_doc({
		"doctype": "Subscription Change", "subscription": sub, "change_type": "Plan Changed",
		"new_value": plan, "locked_rate": rate, "currency": currency, "effective_at": effective_at,
	}).insert(ignore_permissions=True)


def stage_resizes(primary_sub, base_cluster, base_plan, currency, kind):
	"""Two resizes on the current (June) invoice, in one of two shapes:

	  * same_day    — an upsize and a downsize within the SAME calendar day, so the
	                  bill carries two same-day Plan Changed slivers.
	  * within_24h  — an upsize late one evening and a downsize the next morning,
	                  i.e. a second resize inside 24h of the first (spanning midnight).
	"""
	up = plan_name(_plan_after(base_plan, +1))
	down = plan_name(_plan_after(base_plan, 0))  # back to the original size
	if kind == "same_day":
		_add_resize(primary_sub, up, currency, base_cluster, "2026-06-15 09:30:00")
		_add_resize(primary_sub, down, currency, base_cluster, "2026-06-15 16:45:00")
	elif kind == "within_24h":
		_add_resize(primary_sub, up, currency, base_cluster, "2026-06-14 20:00:00")
		_add_resize(primary_sub, down, currency, base_cluster, "2026-06-15 08:00:00")


# --- payment attempts + refunds (terminal-state builders) -------------------


def backdate_invoice(invoice, when):
	"""Pin an invoice's finalisation moment to `when`. The invoice Activity reads
	`creation` as the 'Invoice finalised' event; a demo invoice is generated at seed
	time, so without this it would sort AFTER its own backdated payments — an invoice
	that reads as finalised months after it was paid."""
	frappe.db.set_value(
		"Invoice", invoice, "creation", frappe.utils.get_datetime(when), update_modified=False
	)


def backdate_credit_debits(invoice, when):
	"""Pin an invoice's credit-application moment to `when`.

	The credits-then-card waterfall draws the wallet at invoice-open time — before
	the card is charged — but draw_wallet_credit records the Credit Ledger debit at
	seed time. Without this the 'Credits applied' event (and the 'Invoice settled'
	marker pinned to the latest event) sorts AFTER a backdated card capture: an
	invoice that reads as credited months after its card already settled it."""
	when = frappe.utils.get_datetime(when)
	for e in frappe.get_all(
		"Credit Ledger Entry",
		filters={"reference_type": "Invoice", "reference_name": invoice, "entry_type": "Debit"},
		pluck="name",
	):
		frappe.db.set_value(
			"Credit Ledger Entry", e, {"created_at": when, "creation": when}, update_modified=False
		)


def backdate_welcome_credit(team, when):
	"""Pin the team's one-time welcome (Promotion) credit grant to `when` — its signup.

	provision_billing_profile books the welcome credit at seed time, but the invoices that
	draw it down are backdated. Two things break if the grant is left at seed time:

	  * the wallet timeline shows the credit being *applied* (backdated) before it was
	    *granted* (seed time) — an impossible order;
	  * get_balance (no currency) reads the newest-by-`creation` entry's running_balance,
	    so the stale seed-time grant wins and reports the pre-draw balance (the full grant)
	    instead of what's actually left.

	Backdating the grant's `creation`/`created_at` to before the first period restores
	creation order == insert order, so the draw is the newest row and the balance is right."""
	when = frappe.utils.get_datetime(when)
	for e in frappe.get_all(
		"Credit Ledger Entry",
		filters={"team": team, "reference_type": "Promotion", "entry_type": "Credit"},
		pluck="name",
	):
		frappe.db.set_value(
			"Credit Ledger Entry", e, {"created_at": when, "creation": when}, update_modified=False
		)


def draw_wallet_credit(invoice) -> float:
	"""Run the real credits-leg of settlement (invoicing.open_and_collect, collect=False):
	draw the team's wallet credits against the invoice, recording a Credit Ledger debit and
	`credit_applied`, and leaving the invoice Open for the card to settle the remainder.

	This is the same waterfall production uses (credits first, then card); collect=False
	skips the gateway leg because the demo gateways are offline, so the caller simulates the
	card capture for whatever is returned. Returns the remainder still due after credits."""
	from central.billing.revenue import invoicing

	if frappe.db.get_value("Invoice", invoice, "status") != "Draft":
		frappe.db.set_value("Invoice", invoice, "status", "Draft", update_modified=False)
	invoicing.open_and_collect(invoice, collect=False)
	return frappe.utils.flt(frappe.db.get_value("Invoice", invoice, "expected_collection"))


def _capture_attempt(team, invoice, pm, gateway, amount, currency, when=None):
	"""A successful (Captured) card charge that settled the invoice."""
	when = when or frappe.utils.now_datetime()
	return frappe.get_doc({
		"doctype": "Payment Attempt", "invoice": invoice, "team": team, "gateway": gateway,
		"payment_method": pm, "amount": amount, "currency": currency, "status": "Captured",
		"gateway_transaction_id": f"pi_{frappe.generate_hash(length=20)}", "resolved_by": "Webhook",
		"initiated_at": when, "completed_at": when,
	}).insert(ignore_permissions=True).name


def bank_pending_attempt(team, invoice, pm, gateway, amount, currency):
	"""An in-flight charge: submitted to Stripe, which is still awaiting the bank's
	response (no webhook yet). The attempt is 'Initiated' — reconciliation treats it
	as ambiguous — so the invoice is frozen (no Pay Now / no retry) until it resolves."""
	now = frappe.utils.now_datetime()
	return frappe.get_doc({
		"doctype": "Payment Attempt", "invoice": invoice, "team": team, "gateway": gateway,
		"payment_method": pm, "amount": amount, "currency": currency, "status": "Initiated",
		"gateway_transaction_id": f"pi_{frappe.generate_hash(length=20)}",
		"initiated_at": now,  # completed_at left blank — the bank hasn't answered
	}).insert(ignore_permissions=True).name


def make_refund(team, invoice, attempt, amount, currency, destination, reason, chargeback=False):
	"""A completed Refund against a captured charge. `destination` is 'Source' (back to
	the card — a full double-charge refund or a dispute chargeback) or 'Wallet' (a partial
	overcharge booked as credits). By policy a card/source refund is the FULL-amount case
	and a partial correction always goes to the wallet (refunds.partial_overcharge). A full
	refund to source flips the original attempt to Refunded (mirrors refunds._to_source);
	`chargeback` forces that flip for a dispute. The invoice stays Paid throughout."""
	frappe.get_doc({
		"doctype": "Refund", "payment_attempt": attempt, "invoice": invoice, "team": team,
		"amount": amount, "currency": currency, "destination": destination, "status": "Completed",
		"reason": reason, "gateway_refund_id": f"re_{frappe.generate_hash(length=20)}",
		"created_at": frappe.utils.now_datetime(), "completed_at": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True)
	captured = frappe.utils.flt(frappe.db.get_value("Payment Attempt", attempt, "amount"))
	if chargeback or (destination == "Source" and frappe.utils.flt(amount) >= captured):
		frappe.db.set_value("Payment Attempt", attempt, "status", "Refunded")


# --- activation, composed configs, metered services -------------------------


def activate_team_assets(team):
	"""Flip the team's Pending VM Assets to Running. The Asset.on_update hook then
	enables the linked Subscription (ensure_subscription_enabled) — the same path a
	real provisioned+running VM takes. Without this every subscription stays Disabled."""
	for name in frappe.get_all("Asset", filters={"team": team, "status": "Pending"}, pluck="name"):
		# Change status ON the doc (not via set_value first) so has_value_changed sees
		# Pending→Running and on_update fires ensure_subscription_enabled.
		asset = frappe.get_doc("Asset", name)
		asset.status = "Running"
		asset.save(ignore_permissions=True)


# A valid design-your-own config on the "General" profile (ram = 4×vcpu, disk in range),
# so the à-la-carte selector path is exercised end to end.
_COMPOSED_INCLUDES = [
	{"resource_type": "Compute", "quantity": 2, "unit": "vCPU"},
	{"resource_type": "Memory", "quantity": 8, "unit": "GB"},
	{"resource_type": "Disk", "quantity": 60, "unit": "GB"},
]


def add_composed_subscription(team, cluster, currency, start_date, pm, gateway, resource_id):
	"""Provision a custom VM the customer composed in the selector (ADR 0009): no Plan,
	priced from the à-la-carte component rate card. Returns the subscription name."""
	from central.billing.catalog.subscriptions import provision_composed_subscription

	res = provision_composed_subscription(
		team=team, cluster=cluster, includes=_COMPOSED_INCLUDES, sub_category="General",
		billing_cycle="Monthly", start_date=start_date,
		default_payment_method=pm, gateway=gateway, resource_id=resource_id,
	)
	return res["subscription"]


def subscribe_service(team, service_slug, cluster, pm, gateway):
	"""Subscribe a team to a metered consumer service and return (subscription, subject)."""
	from central.billing.catalog.subscriptions import provision_service_subscription

	res = provision_service_subscription(
		team=team, plan=service_slug, cluster=cluster,
		default_payment_method=pm, gateway=gateway,
	)
	return res["subscription"], res["service_subject"]


def meter_service_usage(subject, resource_type, quantity, unit, period_start, period_end):
	"""Report metered usage for a service subject (resource_id = the synthesized subject).
	ingest_rollup stamps the locked allowance + per-unit rate from the subject's segment,
	so anything past the allowance bills as overage on the period's invoice."""
	from central.billing.platform.sync import record_meter_rollups

	record_meter_rollups([{
		"resource_id": subject, "resource_type": resource_type, "meter_type": "Counter",
		"period_start": f"{period_start} 00:00:00", "period_end": f"{period_end} 23:59:59",
		"quantity": quantity, "unit": unit,
		"idempotency_key": f"{subject}:counter:{period_start}", "status": "closed",
	}])
