# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Per-team admin views: a single team's full billing picture, retention/metrics
rollups, the team table, and the delinquency / payment-failure drill-downs.
"""

import frappe

from central.billing.revenue import credits
from central.billing.authz import require_operator
from central.billing.api.admin._shared import (
	_STANDING_RANK,
	_active_locks,
	_plan_monthly_inr,
	_team_currency,
	_to_inr,
)


@frappe.whitelist()
def get_team_billing(team: str) -> dict:
	"""Team lookup — any team's full billing picture (admin only).

	Amounts here are in the team's OWN billing currency (not INR-normalised) —
	this is the record-level view, so €/$ teams read in their real currency.
	"""
	require_operator()
	currency = _team_currency(team)
	return {
		"team": team,
		"currency": currency,
		"tier": frappe.db.get_value("Trust Tier", team, "tier") or "—",
		"subscriptions": frappe.get_all(
			"Subscription", filters={"team": team},
			fields=["name", "plan", "cluster", "account_standing"]),
		"invoices": frappe.get_all(
			"Invoice", filters={"team": team},
			fields=["name", "status", "total", "amount_paid", "currency", "period_end"], order_by="period_start desc"),
		"payment_attempts": frappe.get_all(
			"Payment Attempt", filters={"team": team},
			fields=["name", "status", "amount", "currency", "gateway", "failure_code", "resolved_by"], order_by="creation desc"),
		"credit_balance": frappe.utils.flt(credits.get_balance(team)["balance"]),
	}


@frappe.whitelist()
def get_retention() -> dict:
	"""Customer retention snapshot: active vs at-risk vs churned, and a retention
	rate. A team is churned when its only standing is suspended; at-risk when
	past_due; retained otherwise."""
	require_operator()
	standing = {}
	for s in frappe.get_all("Subscription", fields=["team", "account_standing"]):
		cur = standing.get(s.team, "Current")
		standing[s.team] = s.account_standing if _STANDING_RANK.get(s.account_standing, 0) > _STANDING_RANK.get(cur, 0) else cur
	total = len(standing)
	active = sum(1 for v in standing.values() if v == "Current")
	at_risk = sum(1 for v in standing.values() if v == "Past Due")
	churned = sum(1 for v in standing.values() if v == "Suspended")
	rows = [{"team": t, "standing": v} for t, v in sorted(standing.items())]
	return {
		"total_teams": total,
		"active": active,
		"at_risk": at_risk,
		"churned": churned,
		"retention_rate": round((total - churned) / total, 3) if total else 0,
		"active_rate": round(active / total, 3) if total else 0,
		"teams": rows,
	}


@frappe.whitelist()
def get_metrics() -> dict:
	"""Headline reports: team counts, on-time vs delinquent, failures, MRR."""
	require_operator()
	subs = frappe.get_all(
		"Subscription", fields=["team", "plan", "cluster", "account_standing", "billing_cycle"]
	)
	teams, mrr = {}, 0.0
	for s in subs:
		rate = _plan_monthly_inr(s.plan, s.cluster)
		mrr += rate / 12 if s.billing_cycle == "Annual" else rate
		cur = teams.get(s.team, "Current")
		teams[s.team] = s.account_standing if _STANDING_RANK.get(s.account_standing, 0) > _STANDING_RANK.get(cur, 0) else cur

	on_time = sum(1 for st in teams.values() if st == "Current")
	team_count = len(teams)
	return {
		"team_count": team_count,
		"paying_on_time": on_time,
		"delinquent": team_count - on_time,            # past_due or suspended
		"suspended": sum(1 for st in teams.values() if st == "Suspended"),
		"payment_failures": frappe.db.count("Payment Attempt", {"status": "Failed"}),
		"mrr": frappe.utils.flt(mrr, 2),
		"active_subscriptions": len(subs),
	}


@frappe.whitelist()
def list_teams() -> list[dict]:
	"""Per-team rollup: standing, tier, MRR, resources, open invoices, credit."""
	require_operator()
	teams = {}
	for s in frappe.get_all("Subscription", fields=["team", "plan", "cluster", "account_standing", "billing_cycle"]):
		t = teams.setdefault(s.team, {"team": s.team, "standing": "Current", "mrr": 0.0, "subscriptions": 0, "resources": 0})
		rate = _plan_monthly_inr(s.plan, s.cluster)
		t["mrr"] += rate / 12 if s.billing_cycle == "Annual" else rate
		t["subscriptions"] += 1
		if _STANDING_RANK.get(s.account_standing, 0) > _STANDING_RANK.get(t["standing"], 0):
			t["standing"] = s.account_standing
	for lock in _active_locks():
		if lock.team in teams:
			teams[lock.team]["resources"] += 1
	rows = []
	for t in teams.values():
		currency = _team_currency(t["team"])
		t["mrr"] = frappe.utils.flt(t["mrr"], 2)
		t["tier"] = frappe.db.get_value("Trust Tier", t["team"], "tier") or "—"
		t["open_invoices"] = frappe.db.count("Invoice", {"team": t["team"], "status": ["in", ["Open", "Overdue"]]})
		t["invoices"] = frappe.db.count("Invoice", {"team": t["team"]})
		# Credit normalised to INR so the whole row reads on one (INR-equiv.) axis.
		t["credit_balance"] = frappe.utils.flt(_to_inr(credits.get_balance(t["team"])["balance"], currency), 2)
		t["currency"] = currency
		rows.append(t)
	return sorted(rows, key=lambda r: r["mrr"], reverse=True)


@frappe.whitelist()
def get_payment_failures(limit: int = 50) -> list[dict]:
	"""Drill-down: which charges are failing and why."""
	require_operator()
	return frappe.get_all(
		"Payment Attempt", filters={"status": "Failed"},
		fields=["name", "team", "invoice", "amount", "currency", "gateway", "failure_code", "failure_reason", "creation"],
		order_by="creation desc", limit=limit)


@frappe.whitelist()
def get_delinquent_teams() -> list[dict]:
	"""Drill-down: who is past_due/suspended + their outstanding invoices."""
	require_operator()
	seen, rows = set(), []
	for s in frappe.get_all("Subscription", filters=[["account_standing", "in", ["Past Due", "Suspended"]]],
			fields=["team", "account_standing"]):
		if s.team in seen:
			continue
		seen.add(s.team)
		overdue = frappe.get_all("Invoice", filters={"team": s.team, "status": ["in", ["Open", "Overdue"]]},
			fields=["name", "status", "total", "amount_paid", "due_date"], order_by="due_date asc")
		rows.append({"team": s.team, "standing": s.account_standing,
			"outstanding": frappe.utils.flt(sum(frappe.utils.flt(i.total) - frappe.utils.flt(i.amount_paid) for i in overdue), 2),
			"invoices": overdue})
	return rows
