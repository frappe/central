# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Comprehensive demo dataset for the billing portal (#demo).

    bench --site demo-billing.local execute central.billing.demo.demo_scenarios.seed

Wipes ALL billing data, then builds a multi-region catalog and TEN teams — five
billing in USD, five in INR — so every dashboard, invoice case and the eleven
billing reports have real, self-consistent data.

Trust tiers (t0 → t3) are assigned one per team, mirrored across the two
currencies: each tier carries the SAME number of paid invoices in USD as in INR
(t0 = 0, t1 = 2, t2 = 5, t3 = 9). Read top-to-bottom that ladder tells the
"upgraded by paying" story — a team climbs a tier by settling more invoices.

Across the ten teams every invoice/payment case is exercised at least once:

  * fixed (plan) billing + metered bandwidth overage
  * multiple VM resizes in a single day, and a second resize within 24h
  * settlement fully from credits; partial-credit-then-card; card capture
  * autopay fallback: the primary card declines and a backup card captures (#28)
  * a payment attempt that fails with a reason, then a dunning (overdue) team
  * a dispute (chargeback → source), a double charge fully refunded (→ source), a partial refund as credits (→ wallet)
  * a charge stuck in-flight (Stripe still awaiting the bank) with the invoice frozen

The catalog shape + record builders live in demo._factory; this module is the
orchestration.
"""

import frappe

from central.billing.catalog import subscriptions
from central.billing.demo._factory import (
	ANCHOR,
	SERVICES,
	STRIPE,
	_add_backup_card,
	_capture_attempt,
	_catalog,
	_ensure_demo_team,
	_ensure_signing_key,
	_failed_attempt,
	_gateway_customer,
	_gateways,
	_month_periods,
	_payment_setup,
	_profile,
	_settle_via_backup,
	_settle_with_retries,
	_tax,
	_team_members,
	_tier,
	_tiers,
	_wipe_all,
	activate_team_assets,
	add_composed_subscription,
	arm_emandate,
	backdate_credit_debits,
	backdate_invoice,
	backdate_welcome_credit,
	bank_pending_attempt,
	draw_wallet_credit,
	make_refund,
	meter_service_usage,
	plan_name,
	set_collection_mode,
	stage_resizes,
	subscribe_service,
)
from central.billing.payments.provisioning import provision_billing_profile
from central.billing.revenue import credits, invoicing

# service plan slug -> (resource_type, unit), for reporting usage against a subject.
_SERVICE_META = {s[2]: (s[1], s[4]) for s in SERVICES}

# Wallet-top-up states settle from credits — no card on file, but a gateway top-up
# still mints a reusable Gateway Customer.
_TOPUP_STATES = ("credits", "credits_full", "free_credits")

# States that spend the team's welcome credit in the CURRENT month, so its historical
# invoices leave the credit untouched (otherwise the current-month credit story has an
# empty wallet). Every other team draws its welcome credit down on its first bill.
_CREDIT_KEPT_STATES = ("partial_card", "credits_full", "credits", "free_credits", "trial")

# Paid invoices per tier, BEFORE the current (June) month. The same ladder applies
# to both currencies, so a USD team and an INR team at the same tier show the same
# invoice count — the visible proof that paying invoices is what promotes a team.
_PAID_MONTHS = {"t0": 0, "t1": 2, "t2": 5, "t3": 9}

# Metered CONSUMER-service subscriptions per team (ADR 0013/0015): the service plan
# slug + the actual item count reported this month. Overage (usage − allowance) bills
# on the current invoice. Allowances (real counts): AI tokens 100000, email 50000,
# PDF 20000 (see SERVICES).
_TEAM_SERVICES = {
	"northwind": [("svc-ai-tokens", 260000), ("svc-pdf", 45000)],  # heavy AI + some PDF
	"initech": [("svc-emails", 130000)],
	"acme-corp": [("svc-ai-tokens", 280000), ("svc-emails", 90000)],
	"umbrella": [("svc-pdf", 75000)],
	"stark-ind": [("svc-emails", 90000)],
}

# Teams that also compose a custom VM in the à-la-carte selector (design-your-own, ADR 0009).
_COMPOSED_TEAMS = ("initech", "umbrella")

# Collection mode per team (ADR 0022), chosen to cover the spectrum on screen.
_COLLECTION_MODES = {
	# INR
	"acme-corp": "Auto Charge",
	"umbrella": "Manual Checkout",
	"stark-ind": "Manual Checkout",
	"hooli": "Manual Checkout",
	"piedpiper": "Prepaid",
	# USD
	"northwind": "Auto Charge",
	"initech": "Auto Charge",
	"soylent": "Auto Charge",
	"globex": "Auto Charge",
	"harbor": "Prepaid",
}

# Card teams: which historical month indices show a failed-then-settled dunning trail
# in the invoice Activity (month index → number of declines before the capture).
_RETRY_HISTORY = {1: 1, 2: 2, 4: 1, 5: 2}

# The most mature team runs a multi-instance fleet, so its invoice carries a long
# line-item table (one line per instance) plus a metered overage.
_FLEET = [
	(cluster, plan)
	for cluster in ("me-dubai", "in-mumbai")
	for plan in ("plan-1vcpu", "plan-2vcpu", "plan-1vcpu", "plan-4vcpu", "plan-2vcpu", "plan-8vcpu")
]

# (slug, tier, currency, state, resources, resize)
#   resources = the team's running instances [(cluster, plan), ...] — any plan in any
#               region; the team bills in ONE currency regardless of where they run.
#   resize    = None | "same_day" | "within_24h" — VM resizes staged on the current bill.
TEAMS = [
	# --- five USD teams, one per rung of the tier ladder ---------------------
	# t3: large fleet (fixed + metered), then a charge stuck in-flight — Stripe is
	# still awaiting the bank, so the current invoice is frozen for any action.
	("northwind", "t3", "USD", "bank_pending", _FLEET, None),
	# t2: current bill settled partly from wallet credits, the remainder on the card.
	("initech", "t2", "USD", "partial_card", [("me-dubai", "plan-4vcpu"), ("in-mumbai", "plan-2vcpu")], None),
	# t1: a paid invoice later charged back — dispute → refunded to source.
	("soylent", "t1", "USD", "dispute", [("me-dubai", "plan-2vcpu")], None),
	# t1: primary card declines, settlement rotates to a backup card that captures (#28);
	# then a double charge by mistake is refunded in full back to the card (→ source).
	("globex", "t1", "USD", "fallback", [("me-dubai", "plan-2vcpu")], None),
	# t0: no history; free credits granted, its first bill settles fully from them.
	# Also resized its VM twice in a single day.
	("harbor", "t0", "USD", "credits_full", [("me-dubai", "plan-1vcpu")], "same_day"),
	# --- five INR teams, mirroring the same tier ladder ----------------------
	# t3: grandfathered launch rate + metered overage; a VM resize within 24h; UPI e-mandate.
	(
		"acme-corp",
		"t3",
		"INR",
		"grandfathered",
		[("in-mumbai", "plan-8vcpu"), ("in-mumbai", "plan-2vcpu"), ("in-mumbai", "plan-1vcpu")],
		"within_24h",
	),
	# t2: dunning — the current invoice is overdue with a trail of failed retries.
	("umbrella", "t2", "INR", "overdue", [("in-mumbai", "plan-4vcpu"), ("in-mumbai", "plan-2vcpu")], None),
	# t1: a payment attempt fails with a reason, then settles on retry (+ metered).
	("stark-ind", "t1", "INR", "retry", [("in-mumbai", "plan-2vcpu")], None),
	# t1: a paid invoice partially refunded as wallet credits (→ wallet).
	("hooli", "t1", "INR", "refund_wallet", [("in-mumbai", "plan-1vcpu")], None),
	# t0: free credits settle its first bill; two VM resizes in one day.
	("piedpiper", "t0", "INR", "credits_full", [("in-mumbai", "plan-1vcpu")], "same_day"),
]


# The demo operator — the first System Manager, who administers billing from Desk
# (the Billing workspace, Plan Configurator, reports).
DEMO_ADMIN = "billing_admin@example.com"
DEMO_ADMIN_PASSWORD = "Billing@2026"


def _ensure_setup_wizard() -> None:
	"""On a fresh (formatted) site the Frappe setup wizard is still pending — complete
	it here so the demo isn't blocked behind it, creating billing_admin@example.com as
	the first System Manager. Idempotent: once setup is complete this only makes sure
	that operator exists (with a Desk login) and is a System Manager."""
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	if not frappe.is_setup_complete():
		setup_complete(
			{
				"language": "English",
				"country": "India",
				"timezone": "Asia/Kolkata",
				"currency": "INR",
				"full_name": "Billing Admin",
				"email": DEMO_ADMIN,
				"password": DEMO_ADMIN_PASSWORD,
			}
		)
		frappe.db.commit()
	_ensure_billing_admin()


def _ensure_billing_admin() -> None:
	"""Guarantee the demo operator exists as a System Manager with a known password,
	even on a site whose setup wizard was completed by someone else."""
	from frappe.utils.password import update_password

	if not frappe.db.exists("User", DEMO_ADMIN):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": DEMO_ADMIN,
				"first_name": "Billing Admin",
				"send_welcome_email": 0,
			}
		)
		user.flags.ignore_password_policy = True
		user.append_roles("System Manager")
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", DEMO_ADMIN)
		if "System Manager" not in {r.role for r in user.roles}:
			user.append_roles("System Manager")
			user.save(ignore_permissions=True)
	update_password(DEMO_ADMIN, DEMO_ADMIN_PASSWORD)


def seed() -> dict:
	"""Wipe all billing data and rebuild the ten-team demo end to end.

	bench --site demo-billing.local execute central.billing.demo.demo_scenarios.seed
	"""
	_ensure_setup_wizard()
	_wipe_all()
	_drop_stray_demo_teams()
	_tiers()
	_catalog()
	_gateways()
	_ensure_signing_key()

	results = {}
	slug_to_team = {}
	for slug, tier, currency, state, resources, resize in TEAMS:
		team = _ensure_demo_team(slug)
		slug_to_team[slug] = team
		results[slug] = _build_team(team, slug, tier, currency, state, resources, resize)

	# Populate the in-app notification feed so the console bell/inbox is demoable —
	# emitted through the REAL writers (the billing sender + the Asset-failed hook),
	# never hand-injected rows.
	_seed_notification_feed(slug_to_team)

	# NOTE: the demo does NOT touch the Billing workspace — the app ships the real
	# "Catalog Administration" workspace as a file fixture (billing/workspace/billing),
	# which `bench migrate` installs. Overwriting it here made the demo site diverge.
	frappe.db.commit()
	return results


def _seed_notification_feed(slug_to_team: dict):
	"""Exercise the notification code paths so every event type + both categories
	(Billing / Server) show up in the console feed for the demo.

	Billing events go through the real `notifications.notify` sender (which records a
	Team Notification via the wired feed); Server Failed is triggered by flipping a
	real Asset to Failed (the `on_update` hook emits it); Resize Failed and
	Cluster Degraded use `engine.dispatch` — the same writer the real hooks use.
	The overdue team already emits Invoice Overdue + Server Suspended via real dunning.
	"""
	from central.billing.platform import notifications
	from central.notification import engine

	# (slug, event_type, extra context) — one representative billing event per team,
	# matched to its scenario. `invoice` context is filled from the team's latest bill.
	billing = [
		("initech", "Payment Success", {}),
		("globex", "Payment Success", {}),
		("globex", "Card Expiry", {"label": "Visa ···· 4242"}),
		("hooli", "Payment Success", {}),
		("stark-ind", "Payment Failure", {"reason": "card_declined"}),
		("stark-ind", "Payment Success", {}),
		("harbor", "Credit Low", {"utilisation": "88%"}),
		("piedpiper", "Credit Low", {"utilisation": "91%"}),
		("acme-corp", "Mandate Reauth", {}),
		("northwind", "Pre-debit Notice", {"amount": "$4,200.00", "charge_on": "2026-07-07"}),
	]
	for slug, event, ctx in billing:
		team = slug_to_team.get(slug)
		if not team:
			continue
		inv = frappe.db.get_value("Invoice", {"team": team}, "name", order_by="creation desc")
		context = dict(ctx)
		context.setdefault("invoice", inv)
		notifications.notify(
			team,
			event,
			context=context,
			reference_doctype="Invoice" if inv else None,
			reference_name=inv,
		)

	# Server Failed — flip one real Running Asset to Failed; the on_update hook fires.
	nw = slug_to_team.get("northwind")
	if nw:
		asset = frappe.db.get_value("Asset", {"team": nw, "status": "Running"}, "name")
		if asset:
			doc = frappe.get_doc("Asset", asset)
			doc.status = "Failed"
			doc.save(ignore_permissions=True)

	# Resize Failed + Cluster Degraded — the same writer the real hooks use.
	acme = slug_to_team.get("acme-corp")
	if acme:
		engine.ensure_event_type(
			"resize_failed",
			category="Server",
			severity="Error",
			required_cap="server:view",
			in_app_title="Resize failed: {{ reference_name }}",
			in_app_body="Server resize failed for {{ reference_name }}: {{ message }}",
			action_label="View server",
			action_route="/servers",
		)
		engine.dispatch(
			acme,
			"resize_failed",
			message="A background resize could not be applied and was rolled "
			"back. Billing stayed on the previous plan. You can retry the resize.",
		)
	umbrella = slug_to_team.get("umbrella")
	if umbrella:
		engine.ensure_event_type(
			"cluster_degraded",
			category="Server",
			severity="Warning",
			required_cap="server:view",
			in_app_title="Region unavailable: {{ reference_name }}",
			in_app_body="Region {{ reference_name }}: {{ message }}",
			action_label="View servers",
			action_route="/servers",
		)
		engine.dispatch(
			umbrella,
			"cluster_degraded",
			message="Central couldn't reach in-mumbai on the last sync. Your servers keep running; "
			"their status in the console may be delayed until the region recovers.",
			reference_doctype="Atlas Instance",
			reference_name="in-mumbai",
		)


# Back-compat alias — older docs/scripts call seed_all().
seed_all = seed


def summary() -> dict:
	"""Post-seed sanity view: a per-team roll-up of every seeded scenario, plus the
	aggregate counts. `teams` reads the state of the demo data at a glance — invoices
	generated, credits allocated vs applied, payments processed, and disputes/refunds.

	    bench --site demo-billing.local execute central.billing.demo.demo_scenarios.summary
	"""
	by_currency: dict[str, int] = {}
	for p in frappe.get_all("Billing Profile", fields=["currency"]):
		by_currency[p.currency] = by_currency.get(p.currency, 0) + 1

	line_counts = {
		inv: frappe.db.count("Invoice Line Item", {"parent": inv})
		for inv in frappe.get_all("Invoice", pluck="name")
	}
	top = max(line_counts, key=line_counts.get) if line_counts else None

	return {
		"teams": [
			_team_summary(slug, tier, currency, state)
			for slug, tier, currency, state, _resources, _resize in TEAMS
		],
		"totals": {
			"teams_by_currency": by_currency,
			"paid_invoices": frappe.db.count("Invoice", {"status": "Paid"}),
			"open_invoices": frappe.db.count("Invoice", {"status": "Open"}),
			"overdue_invoices": frappe.db.count("Invoice", {"status": "Overdue"}),
			"failed_attempts": frappe.db.count("Payment Attempt", {"status": "Failed"}),
			"in_flight_attempts": frappe.db.count("Payment Attempt", {"status": "Initiated"}),
			"refunds": {
				r.destination: frappe.db.count("Refund", {"destination": r.destination})
				for r in frappe.get_all("Refund", fields=["destination"], group_by="destination")
			},
			"resizes": frappe.db.count("Subscription Change", {"change_type": "Plan Changed"}),
			"credit_ledger_entries": frappe.db.count("Credit Ledger Entry"),
			"usage_rollups": frappe.db.count("Usage Rollup"),
			"largest_invoice": {"invoice": top, "line_items": line_counts.get(top)} if top else None,
			"months_covered": sorted(
				{str(d)[:7] for d in frappe.get_all("Invoice", pluck="period_start") if d}
			),
		},
	}


def _sum(doctype: str, filters: dict, field: str = "amount") -> float:
	"""Total `field` over the rows matching `filters` (money stays in one currency
	per team, so a plain sum is safe)."""
	rows = frappe.get_all(doctype, filters=filters, fields=[field])
	return frappe.utils.flt(sum(frappe.utils.flt(r.get(field)) for r in rows), 2)


def _team_summary(slug: str, tier: str, currency: str, state: str) -> dict:
	"""One team's scenario roll-up. Keyed by the readable demo slug and labelled with
	its scenario `state`, so the demo data is legible without decoding TEAM-000N ids."""
	team = frappe.db.get_value("Team", {"owner_user": f"owner-{slug}@example.com"}, "name")
	if not team:
		return {"team": slug, "state": state, "seeded": False}

	invoices_by_status: dict[str, int] = {}
	for status in frappe.get_all("Invoice", filters={"team": team}, pluck="status"):
		invoices_by_status[status] = invoices_by_status.get(status, 0) + 1
	# A chargeback (dispute) is the only path that flips a captured attempt to Refunded;
	# a plain refund leaves the capture intact. So Refunded attempts == disputes.
	return {
		"team": slug,
		"state": state,
		"tier": tier,
		"currency": currency,
		"invoices": {"total": sum(invoices_by_status.values()), "by_status": invoices_by_status},
		"credits_allocated": _sum("Credit Ledger Entry", {"team": team, "entry_type": "Credit"}),
		"credits_applied": _sum("Credit Ledger Entry", {"team": team, "entry_type": "Debit"}),
		"payments_captured": {
			"count": frappe.db.count("Payment Attempt", {"team": team, "status": "Captured"}),
			"amount": _sum("Payment Attempt", {"team": team, "status": "Captured"}),
		},
		"payments_failed": frappe.db.count("Payment Attempt", {"team": team, "status": "Failed"}),
		"refunds": {
			"count": frappe.db.count("Refund", {"team": team}),
			"amount": _sum("Refund", {"team": team}),
			"by_destination": {
				r.destination: frappe.db.count("Refund", {"team": team, "destination": r.destination})
				for r in frappe.get_all(
					"Refund", filters={"team": team}, fields=["destination"], group_by="destination"
				)
			},
		},
		"disputes": frappe.db.count("Payment Attempt", {"team": team, "status": "Refunded"}),
	}


def _drop_stray_demo_teams() -> None:
	"""Remove any member-less, slug-named teams an earlier seed left behind (the
	bootstrap teams named "<Owner>'s Team" are kept and reused)."""
	slugs = [t[0] for t in TEAMS]
	for name in frappe.get_all("Team", filters={"team_name": ["in", slugs]}, pluck="name"):
		frappe.delete_doc("Team", name, force=True, ignore_permissions=True)
	frappe.db.commit()


# --- per-team build ---------------------------------------------------------


def _build_team(team, slug, tier, currency, state, resources, resize):
	from collections import OrderedDict

	_tax(team, currency)
	_profile(team, slug, currency, resources[0][0])
	_tier(team, tier)  # tier lives on the Billing Profile, so set it after _profile
	# Signup provisioning grants the welcome credits once, in the team's currency and at
	# the amount Billing Settings carries — the same rule production runs, not a random grant.
	provision_billing_profile(team)
	_team_members(team, slug)  # members on varied system roles + a custom role
	gateway, pm = _payment_setup(team, slug, currency, state)
	# A top-up-only team has no card, but its wallet top-up still mints a customer.
	if pm is None and state in _TOPUP_STATES:
		_gateway_customer(team, STRIPE, f"cus_{slug}")
	# A fallback team keeps a second, lower-priority card so settlement can rotate to it
	# when the primary declines (#28).
	if state == "fallback":
		_add_backup_card(team, slug, gateway)

	periods = _month_periods(_PAID_MONTHS[tier])
	first_start = periods[0][0] if periods else ANCHOR
	# Welcome credits are granted at signup — backdate the grant to before the team's
	# first period so the wallet timeline reads grant → apply (not apply → grant) and the
	# balance is read off the actual draw, not the stale seed-time grant.
	backdate_welcome_credit(team, f"{first_start} 00:00:00")

	by_cluster = OrderedDict()
	for cluster, plan in resources:
		by_cluster.setdefault(cluster, []).append(plan)

	# One subscription per cluster carries the per-region billing intent. The first
	# cluster of a grandfathered team locks the launch (discounted) rate; the rest lock
	# today's catalog rate. The customer sees ONE consolidated invoice per month.
	subs = []
	idx = 0
	for cluster, plans in by_cluster.items():
		idx += 1
		plan = plan_name(plans[0])  # logical key -> the configurator-minted Plan name
		resource = f"srv-{slug}-{idx}"
		catalog = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
		rate = round(catalog * 0.78, 2) if (state == "grandfathered" and idx == 1) else catalog
		sub = subscriptions.create_subscription(
			team=team,
			cluster=cluster,
			plan=plan,
			billing_cycle="Monthly",
			default_payment_method=pm,
			gateway=gateway,
			start_date=first_start,
			resource_id=resource,
		).name
		opening = frappe.db.get_value(
			"Subscription Change", {"subscription": sub, "change_type": "Created"}, "name"
		)
		if opening:
			frappe.db.set_value(
				"Subscription Change",
				opening,
				{"locked_rate": rate, "effective_at": f"{first_start} 00:00:00"},
				update_modified=False,
			)
		subs.append(sub)
	primary_sub = subs[0]

	# A custom VM the customer composed in the à-la-carte selector (no preset Plan).
	if slug in _COMPOSED_TEAMS:
		add_composed_subscription(team, resources[0][0], currency, first_start, pm, gateway, f"cmp-{slug}")

	# Take every VM/composed Asset Running so its subscription enables (the real path).
	activate_team_assets(team)

	# Metered consumer services (AI tokens / email / PDF): subscribe + report this
	# month's usage; overage past the bundled allowance bills on the current invoice.
	for svc_slug, usage in _TEAM_SERVICES.get(slug, []):
		_sub, subject = subscribe_service(team, plan_name(svc_slug), resources[0][0], pm, gateway)
		resource_type, unit = _SERVICE_META[svc_slug]
		meter_service_usage(subject, resource_type, usage, unit, ANCHOR, "2026-06-30")

	# VM resize(s) staged on the current month's bill (multiple in a day / within 24h).
	if resize:
		stage_resizes(primary_sub, resources[0][0], resources[0][1], currency, resize)

	# Historical months — each a consolidated invoice, all settled to Paid (a few via
	# a dunning-then-capture trail so the invoice Activity + failed_payments report fill).
	for i, (start, end) in enumerate(periods):
		inv = invoicing.generate_team_invoice(team, start, end, subscription=primary_sub)
		if not inv:
			continue
		# Finalised the morning the period closed — before that month's payment attempts.
		backdate_invoice(inv, f"{end} 08:00:00")
		# The overdue team's most recent bill is left unpaid and dunned to Overdue +
		# suspended. Anchoring it to a CLOSED month (due 7 days after the month ended)
		# means the whole cycle — decline retries, Day-7 Overdue, Day-14 suspend — sits
		# in the past, so the timeline reads finalised -> declines -> overdue in order.
		# A current-month bill can't: finalised only at month end, it has no room to go
		# overdue before 'today'.
		if state == "overdue" and i == len(periods) - 1:
			_run_overdue_cycle(team, inv, pm, gateway, frappe.utils.add_days(end, 7))
			continue
		# Real credits-then-card waterfall: draw the wallet credit first (a Credit Ledger
		# debit + credit_applied), then the card settles the remainder. Credit-scenario
		# teams keep their welcome credit for the current-month story.
		remainder = frappe.utils.flt(frappe.db.get_value("Invoice", inv, "expected_collection"))
		if state not in _CREDIT_KEPT_STATES:
			remainder = draw_wallet_credit(inv)
			# Credits are drawn at invoice-open time, before the card — pin the debit to
			# the finalisation moment so it sorts ahead of that month's card attempts.
			backdate_credit_debits(inv, f"{end} 08:00:00")
			if frappe.db.get_value("Invoice", inv, "status") == "Paid":
				continue  # welcome credit covered it in full — no card needed
		retries = _RETRY_HISTORY.get(i, 0) if pm else 0
		if retries:
			_settle_with_retries(team, inv, pm, gateway, retries, remainder, currency)
		else:
			# No dunning trail this month — a single card capture settles the remainder
			# after credits. Record it (backdated to the morning after finalisation) so the
			# payment history is complete; without it the invoice reads as Paid with the
			# card portion collected but no card charge ever shown.
			if remainder > 0 and pm:
				_capture_attempt(team, inv, pm, gateway, remainder, currency, when=f"{end} 09:00:00")
			frappe.db.set_value(
				"Invoice",
				inv,
				{
					"status": "Paid",
					"amount_paid": remainder,
					"due_date": frappe.utils.add_days(end, 7),
				},
			)

	note = _finish_current_month(team, primary_sub, currency, state, pm, gateway)

	mode = _COLLECTION_MODES.get(slug, "Auto Charge" if currency != "INR" else "Prepaid")
	set_collection_mode(team, mode)
	if mode == "Auto Charge" and currency == "INR":
		arm_emandate(team)
	final_mode = frappe.db.get_value("Billing Profile", team, "collection_mode")
	return f"{len(resources)} instance(s) across {len(by_cluster)} region(s) — {note} [{final_mode}]"


def _run_overdue_cycle(team, inv, pm, gateway, due):
	"""Leave `inv` unpaid and drive it through the REAL dunning cycle to Overdue +
	suspended. Three declined retries (a day apart from `due`) seed the failure trail;
	dunning.process_invoice_dunning then escalates at Day 7 (Overdue + past_due +
	notification) and Day 14 (suspend directive) — the real stages, not a hand-set
	status. With `due` on a closed month, the whole cycle lands before 'today'."""
	from central.billing.revenue import dunning

	frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": due, "amount_paid": 0})
	# Seed the declined retries (offline). With every method already failed, the real
	# dunning has nothing left to charge, so it escalates without a gateway round-trip.
	base = frappe.utils.get_datetime(f"{due} 09:00:00")
	for n in range(3):
		_failed_attempt(team, inv, pm, gateway, n, when=frappe.utils.add_to_date(base, days=n))
	due_d = frappe.utils.getdate(due)
	dunning.process_invoice_dunning(inv, now=frappe.utils.add_days(due_d, 7))
	dunning.process_invoice_dunning(inv, now=frappe.utils.add_days(due_d, 14))


def _finish_current_month(team, sub, currency, state, pm, gateway):
	"""Build the current (June) invoice — one consolidated invoice — in the team's
	terminal state, exercising one settlement / refund / dunning path each."""
	inv = invoicing.generate_team_invoice(team, ANCHOR, "2026-06-30", subscription=sub)
	if not inv:
		return state
	# Finalised end of the current month — before this month's settlement/refund events.
	backdate_invoice(inv, "2026-06-30 08:00:00")
	total = frappe.utils.flt(frappe.db.get_value("Invoice", inv, "total"))
	collectable = frappe.utils.flt(frappe.db.get_value("Invoice", inv, "expected_collection"))

	# --- charge stuck in-flight — Stripe still awaiting the bank -----------------
	if state == "bank_pending":
		frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": "2026-07-07"})
		bank_pending_attempt(team, inv, pm, gateway, collectable, currency)
		return "charge in-flight (awaiting bank) — invoice frozen"

	# --- partial credit, remainder captured on the card -------------------------
	if state == "partial_card":
		# Draw down the team's wallet (its welcome credit) first, then charge the rest.
		balance = frappe.utils.flt(credits.get_balance(team)["balance"])
		applied = round(min(balance, collectable), 2)
		if applied > 0:
			credits.apply_credit(
				team,
				applied,
				currency,
				reference_type="Invoice",
				reference_name=inv,
				note=f"Credit applied to {inv}",
			)
		remainder = round(collectable - applied, 2)
		_capture_attempt(team, inv, pm, gateway, remainder, currency)
		frappe.db.set_value(
			"Invoice",
			inv,
			{
				"status": "Paid",
				"credit_applied": applied,
				"expected_collection": remainder,
				"amount_paid": remainder,
				"due_date": "2026-07-07",
			},
		)
		return f"part from credits ({applied}), remainder captured on card"

	# --- dispute: charge captured, then charged back to source ------------------
	if state == "dispute":
		frappe.db.set_value(
			"Invoice", inv, {"status": "Paid", "amount_paid": total, "due_date": "2026-07-07"}
		)
		attempt = _capture_attempt(team, inv, pm, gateway, total, currency)
		make_refund(
			team, inv, attempt, total, currency, "Source", "Cardholder dispute — chargeback", chargeback=True
		)
		return "Paid then disputed — full chargeback to source"

	# --- autopay fallback: primary declines, a backup card captures -------------
	# Then a double charge by mistake: the same invoice is captured a second time on
	# the backup card, and that duplicate is refunded in FULL back to the card. A card
	# (source) refund is always the full-amount case — a partial correction always goes
	# to the wallet instead (see refund_wallet).
	if state == "fallback":
		# Open first, so the fallback reads as a real collection run before it settles.
		frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": "2026-07-07"})
		_attempt, backup_pm = _settle_via_backup(
			team, inv, pm, gateway, collectable, currency, when="2026-06-30 09:00:00"
		)
		# Duplicate capture on the same invoice, then its full refund to source.
		dup = _capture_attempt(
			team, inv, backup_pm, gateway, collectable, currency, when="2026-06-30 11:00:00"
		)
		make_refund(team, inv, dup, collectable, currency, "Source", "Duplicate charge — full refund to card")
		return "primary declined → backup captured (#28); duplicate charge refunded in full → source"

	# --- refund as credits (→ wallet) -------------------------------------------
	if state == "refund_wallet":
		frappe.db.set_value(
			"Invoice", inv, {"status": "Paid", "amount_paid": total, "due_date": "2026-07-07"}
		)
		attempt = _capture_attempt(team, inv, pm, gateway, total, currency)
		refund_amt = round(total * 0.15, 2)
		make_refund(team, inv, attempt, refund_amt, currency, "Wallet", "Partial overcharge")
		credits.refund_to_wallet(
			team,
			refund_amt,
			currency=currency,
			reference_type="Refund",
			reference_name=f"{team}-refund",
			note="Partial overcharge → wallet",
		)
		return "Paid + partial refund → wallet (credits)"

	# --- dunning: the overdue bill is the last CLOSED month (built + dunned in the
	# historical loop, where the cycle fits before 'today'). The current month is a
	# fresh, not-yet-due Open invoice — realistic for a team carrying an overdue bill.
	if state == "overdue":
		frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": "2026-07-07", "amount_paid": 0})
		return "prior month overdue → suspended; current month open"

	# --- one failed attempt (with reason), then settled on retry ----------------
	if state == "retry":
		_settle_with_retries(team, inv, pm, gateway, 1, collectable, currency)
		frappe.db.set_value("Invoice", inv, "due_date", "2026-07-07")
		return "1 declined attempt (card_declined) then captured"

	# --- full settlement from the welcome credits -------------------------------
	if state == "credits_full":
		invoicing.open_and_collect(inv)  # welcome credits cover it in full → Paid
		return "settled fully from welcome credits (no card touched)"

	# active / grandfathered — leave the current invoice Open.
	frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": "2026-07-07"})
	return (
		"grandfathered (locked launch rate), open current invoice"
		if state == "grandfathered"
		else "active, open current invoice"
	)
