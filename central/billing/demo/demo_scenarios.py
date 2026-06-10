# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Comprehensive demo dataset for the billing portal (#demo).

    bench --site central.local execute central.billing.demo.demo_scenarios.seed_all

Wipes ALL billing data, then builds a realistic multi-region catalog and
ten teams so every dashboard criterion can be demonstrated:

* 3 clusters — India (Mumbai), Europe (Frankfurt), Middle East (Dubai).
* 5 plan sizes (1→16 vCPU), each priced per cluster x currency (INR/EUR/USD),
  so a team paying in one currency can subscribe to any region.
* 4 trust tiers (t0 trial → t3 enterprise). Higher-tier teams carry ~10 months
  of paid invoices; lower tiers a month or two.
* Mixed currencies, including INR-paying teams running in EU / Middle East.
* A grandfathering example: a long-standing team billed at its locked launch
  rate while the catalog price has since risen (price-lock discrepancy).
* Per-team states: active, overdue/dunning, suspended, prepaid credits, refund,
  and a free-trial cost report.

The catalog shape + record builders live in demo._factory; this module is the
orchestration. The Agent-side mirror lives in press_billing_agent.demo.seed.
"""

import frappe

from central.billing.revenue import invoicing, credits
from central.billing.platform import notifications
from central.billing.catalog import subscriptions
from central.billing.platform.sync import receive_meter_rollups, receive_usage_events
from central.billing.demo._factory import (
	ANCHOR,
	PLAN_SIZES,
	_catalog,
	_ensure_demo_team,
	_ensure_signing_key,
	_failed_attempt,
	_gateways,
	_month_periods,
	_payment_setup,
	_profile,
	_tax,
	_tier,
	_tiers,
	_wipe_all,
)

# (team, tier, currency, paid_months, state, resources)
#   paid_months = closed Paid invoices per cluster before the current (June) month.
#   resources   = the team's running instances [(cluster, plan), ...] — droplet-
#                 style: any plan in any region, capped by the tier. A team bills
#                 in ONE currency regardless of where its instances run.
TEAMS = [
	("acme-corp", "t3", "INR", 9, "Grandfathered", [
		("in-mumbai", "plan-8vcpu"), ("in-mumbai", "plan-2vcpu"),
		("eu-frankfurt", "plan-4vcpu"), ("me-dubai", "plan-1vcpu")]),
	("globex", "t3", "EUR", 9, "Active", [
		("eu-frankfurt", "plan-16vcpu"), ("eu-frankfurt", "plan-4vcpu"),
		("in-mumbai", "plan-2vcpu")]),
	("initech", "t2", "USD", 5, "Active", [
		("me-dubai", "plan-4vcpu"), ("me-dubai", "plan-1vcpu"), ("eu-frankfurt", "plan-2vcpu")]),
	("umbrella", "t2", "INR", 5, "Active", [            # INR billing, EU + India
		("eu-frankfurt", "plan-4vcpu"), ("in-mumbai", "plan-2vcpu")]),
	("wayne-ent", "t2", "INR", 5, "Active", [           # INR billing, ME + India
		("me-dubai", "plan-2vcpu"), ("in-mumbai", "plan-1vcpu")]),
	("stark-ind", "t1", "INR", 1, "overdue", [("in-mumbai", "plan-2vcpu")]),
	("cyberdyne", "t1", "EUR", 1, "Suspended", [("eu-frankfurt", "plan-2vcpu")]),
	("hooli", "t1", "INR", 1, "credits", [("in-mumbai", "plan-1vcpu")]),
	("soylent", "t1", "USD", 1, "refund", [("me-dubai", "plan-2vcpu")]),
	("piedpiper", "t0", "INR", 0, "trial", [("in-mumbai", "plan-1vcpu")]),
]


def seed_all() -> dict:
	_wipe_all()
	_tiers()
	_catalog()
	_gateways()
	_ensure_signing_key()

	results = {}
	for slug, tier, currency, months, state, resources in TEAMS:
		# `team` is now a Link → Team: mint/resolve a real Team and store its name
		# on every record; the slug stays for human-readable labels.
		team = _ensure_demo_team(slug)
		results[slug] = _build_team(team, slug, tier, currency, months, state, resources)

	from central.billing.demo.demo import _ensure_workspace

	_ensure_workspace()
	# Administrator is a System Manager (operator) — they browse any team and
	# _default_team() lands them on a team with data; no per-user team link needed.
	frappe.db.commit()
	return results


# --- per-team build ---------------------------------------------------------


def _build_team(team, slug, tier, currency, months, state, resources):
	from collections import OrderedDict

	_tier(team, tier)
	_tax(team, currency)
	_profile(team, slug, currency, resources[0][0], prepaid=(state == "credits"))
	gateway, pm = _payment_setup(team, slug, currency, state)

	periods = _month_periods(months)
	first_start = periods[0][0] if periods else ANCHOR

	by_cluster = OrderedDict()
	for cluster, plan in resources:
		by_cluster.setdefault(cluster, []).append(plan)

	# Provision every instance — one price-lock each. The first instance carries
	# the grandfathered (locked launch) rate; the rest lock today's catalog rate.
	idx = 0
	for cluster, plans in by_cluster.items():
		for plan in plans:
			idx += 1
			resource = f"srv-{slug}-{idx}"
			catalog = frappe.get_doc("Plan", plan).get_rate(currency, cluster)
			rate = round(catalog * 0.78, 2) if (state == "Grandfathered" and idx == 1) else catalog
			receive_usage_events([{
				"event_id": f"ev-{slug}-{idx}", "team": team, "resource_id": resource,
				"cluster": cluster, "plan": plan, "shown_rate": rate, "currency": currency,
				"event_type": "subscribed", "effective_from": f"{first_start} 00:00:00", "effective_to": None,
			}])
			# A metered bandwidth overage on the first active instance.
			if idx == 1 and state in ("Grandfathered", "Active", "credits"):
				allowance = next(p[5] for p in PLAN_SIZES if p[0] == plan)
				receive_meter_rollups([{
					"resource_id": resource, "resource_type": "Transfer", "meter_type": "Counter",
					"period_start": f"{ANCHOR} 00:00:00", "period_end": "2026-06-30 23:59:59",
					"quantity": round(allowance * 1.25), "unit": "GB",
					"idempotency_key": f"{resource}:counter:{ANCHOR}", "status": "closed",
				}])

	# One subscription per cluster carries the per-region billing intent (and the
	# default payment method that funds the auto-charge). But the customer sees a
	# SINGLE consolidated invoice per month — generate_team_invoice rolls every
	# cluster's day-weighted lines + overage into one Invoice per period.
	subs = []
	for cluster, plans in by_cluster.items():
		subs.append(subscriptions.create_subscription(
			team=team, cluster=cluster, plan=plans[0], billing_cycle="Monthly",
			default_payment_method=pm, gateway=gateway,
		).name)
	primary_sub = subs[0]

	for start, end in periods:
		inv = invoicing.generate_team_invoice(team, start, end, subscription=primary_sub)
		if inv:
			total = frappe.db.get_value("Invoice", inv, "expected_collection")
			frappe.db.set_value("Invoice", inv, {
				"status": "Paid", "amount_paid": total, "due_date": frappe.utils.add_days(end, 7),
			})

	note = _finish_current_month(team, primary_sub, currency, state, pm, gateway)
	return f"{len(resources)} instances across {len(by_cluster)} region(s) — {note}"


def _set_team_standing(team, standing, changed_by="dunning"):
	"""Move every one of the team's subscriptions to a standing (the team — not a
	single region — is past_due/suspended)."""
	for s in frappe.get_all("Subscription", {"team": team}, pluck="name"):
		subscriptions.set_standing(s, standing, changed_by=changed_by)


def _finish_current_month(team, sub, currency, state, pm, gateway):
	"""Build the open/June invoice (one consolidated invoice) in the team's terminal state."""
	if state == "trial":
		inv = invoicing.generate_team_invoice(team, ANCHOR, "2026-06-30", subscription=sub)
		if inv:
			invoicing.open_and_collect(inv)  # cost_report → opened, never charged
		return "trial cost report"

	inv = invoicing.generate_team_invoice(team, ANCHOR, "2026-06-30", subscription=sub)
	if not inv:
		return state

	if state == "overdue":
		frappe.db.set_value("Invoice", inv, {"status": "Overdue", "due_date": "2026-06-01", "amount_paid": 0})
		_set_team_standing(team, "Past Due")
		for n in range(3):
			_failed_attempt(team, inv, pm, gateway, n)
			notifications.notify(team, "Payment Retry",
				message=f"Payment retry {n + 1} for {inv} failed: card_declined",
				reference_doctype="Invoice", reference_name=inv)
		notifications.notify(team, "Invoice Overdue", context={"invoice": inv},
			reference_doctype="Invoice", reference_name=inv)
		return "Overdue + past_due + 3 failed retries"

	if state == "Suspended":
		frappe.db.set_value("Invoice", inv, {"status": "Overdue", "due_date": "2026-05-20", "amount_paid": 0})
		_set_team_standing(team, "Past Due")
		# Suspension follows EXHAUSTED dunning — the card on file was charged and
		# declined on each retry. Those attempts are non-negotiable history.
		for n in range(3):
			_failed_attempt(team, inv, pm, gateway, n)
			notifications.notify(team, "Payment Retry",
				message=f"Payment retry {n + 1} for {inv} failed: card_declined",
				reference_doctype="Invoice", reference_name=inv)
		_set_team_standing(team, "Suspended")
		from central.billing.catalog.entitlements import issue_token

		issue_token(team, {}, suspend=True)
		notifications.notify(team, "Invoice Overdue", context={"invoice": inv},
			reference_doctype="Invoice", reference_name=inv)
		return "Suspended + 3 failed retries + cap-0 suspend token"

	if state == "credits":
		# Deliberately under-fund so the prepaid shortfall + credit alert show.
		credits.purchase(team, 1000, currency, note="Demo top-up")
		invoicing.open_and_collect(inv)  # credits-first; remainder Open for dunning
		return "prepaid credits applied + Open remainder (shortfall)"

	if state == "refund":
		total = frappe.db.get_value("Invoice", inv, "total")
		frappe.db.set_value("Invoice", inv, {"status": "Paid", "amount_paid": total, "due_date": "2026-07-07"})
		attempt = frappe.get_doc({
			"doctype": "Payment Attempt", "invoice": inv, "team": team, "gateway": gateway,
			"payment_method": pm, "amount": total, "currency": currency, "status": "Captured",
			"gateway_transaction_id": f"pi_{team}", "resolved_by": "Webhook",
		}).insert(ignore_permissions=True).name
		frappe.get_doc({
			"doctype": "Refund", "payment_attempt": attempt, "invoice": inv, "team": team,
			"amount": round(total * 0.1, 2), "currency": currency, "destination": "Wallet",
			"status": "Completed", "reason": "Partial overcharge",
			"created_at": frappe.utils.now_datetime(), "completed_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True)
		credits.refund_to_wallet(team, round(total * 0.1, 2), currency=currency,
			reference_type="Refund", reference_name=f"{team}-partial", note="Partial overcharge")
		return "Paid + partial refund → wallet"

	# active / grandfathered
	frappe.db.set_value("Invoice", inv, {"status": "Open", "due_date": "2026-07-07"})
	return "grandfathered (locked launch rate)" if state == "Grandfathered" else "active, open current invoice"
