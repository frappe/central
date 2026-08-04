# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Cost-Explorer financial aggregates: billed/collected/outstanding, the revenue
trend chart, spend breakdowns, payment success rates, aging, and trial subsidy.
"""

import frappe

from central.billing.api.admin._shared import (
	_FX_TO_INR,
	_MONTHS,
	AGING_BUCKETS,
	_period_filter,
	_to_inr,
)
from central.billing.authz import require_operator


@frappe.whitelist()
def get_summary(from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Total billed / collected / outstanding across all teams (INR-equivalent)."""
	require_operator()
	invoices = frappe.get_all(
		"Invoice",
		filters=[["invoice_type", "=", "Billable"]] + _period_filter("period_start", from_date, to_date),
		fields=["status", "total", "amount_paid", "currency"],
	)
	billed = sum(_to_inr(i.total, i.currency) for i in invoices)
	collected = sum(_to_inr(i.amount_paid, i.currency) for i in invoices)
	outstanding = sum(
		_to_inr(i.total, i.currency) - _to_inr(i.amount_paid, i.currency)
		for i in invoices
		if i.status in ("Open", "Overdue")
	)
	by_status = {}
	for i in invoices:
		by_status[i.status] = by_status.get(i.status, 0) + 1
	return {
		"total_billed": frappe.utils.flt(billed, 2),
		"total_collected": frappe.utils.flt(collected, 2),
		"outstanding": frappe.utils.flt(outstanding, 2),
		"invoice_count": len(invoices),
		"by_status": by_status,
		"currency": "INR",
	}


@frappe.whitelist()
def get_revenue_trend(months: int = 12) -> list[dict]:
	"""Monthly billed vs collected (INR-normalised) — the headline revenue chart.

	Invoices carry mixed currencies, so each is converted to INR at a flat demo FX
	rate before bucketing by billing month, giving one comparable revenue axis.
	"""
	require_operator()
	buckets = {}
	for inv in frappe.get_all(
		"Invoice",
		filters={"invoice_type": "Billable"},
		fields=["period_start", "total", "amount_paid", "currency"],
	):
		if not inv.period_start:
			continue
		key = str(inv.period_start)[:7]  # YYYY-MM
		fx = _FX_TO_INR.get(inv.currency, 1.0)
		b = buckets.setdefault(key, {"billed": 0.0, "collected": 0.0})
		b["billed"] += frappe.utils.flt(inv.total) * fx
		b["collected"] += frappe.utils.flt(inv.amount_paid) * fx
	rows = []
	for key in sorted(buckets)[-months:]:
		y, m = key.split("-")
		rows.append(
			{
				"month": key,
				"label": f"{_MONTHS[int(m) - 1]} {y[2:]}",
				"billed": frappe.utils.flt(buckets[key]["billed"], 2),
				"collected": frappe.utils.flt(buckets[key]["collected"], 2),
			}
		)
	return rows


@frappe.whitelist()
def get_cluster_breakdown(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
	"""Spend by cluster, from the billable invoices' line items."""
	require_operator()
	invoices = frappe.get_all(
		"Invoice",
		filters=[["invoice_type", "=", "Billable"]] + _period_filter("period_start", from_date, to_date),
		pluck="name",
	)
	if not invoices:
		return []
	totals = {}
	for li in frappe.get_all(
		"Invoice Line Item", filters={"parent": ["in", invoices]}, fields=["cluster", "amount"]
	):
		totals[li.cluster] = totals.get(li.cluster, 0) + frappe.utils.flt(li.amount)
	return [{"cluster": c or "global", "amount": frappe.utils.flt(a, 2)} for c, a in sorted(totals.items())]


@frappe.whitelist()
def get_team_breakdown(from_date: str | None = None, to_date: str | None = None) -> list[dict]:
	"""Spend by team (billable invoice totals)."""
	require_operator()
	totals = {}
	for i in frappe.get_all(
		"Invoice",
		filters=[["invoice_type", "=", "Billable"]] + _period_filter("period_start", from_date, to_date),
		fields=["team", "total"],
	):
		totals[i.team] = totals.get(i.team, 0) + frappe.utils.flt(i.total)
	rows = [{"team": t, "amount": frappe.utils.flt(a, 2)} for t, a in totals.items()]
	return sorted(rows, key=lambda r: r["amount"], reverse=True)


@frappe.whitelist()
def get_payment_analytics(from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Attempt → success rate by gateway + failure-reason tally."""
	require_operator()
	attempts = frappe.get_all(
		"Payment Attempt",
		filters=_period_filter("initiated_at", from_date, to_date),
		fields=["gateway", "status", "failure_code"],
	)
	by_gateway = {}
	failure_reasons = {}
	for a in attempts:
		g = by_gateway.setdefault(a.gateway or "unknown", {"total": 0, "captured": 0})
		g["total"] += 1
		if a.status == "Captured":
			g["captured"] += 1
		elif a.status == "Failed":
			failure_reasons[a.failure_code or "unknown"] = (
				failure_reasons.get(a.failure_code or "unknown", 0) + 1
			)
	for g in by_gateway.values():
		g["success_rate"] = round(g["captured"] / g["total"], 3) if g["total"] else 0
	return {"by_gateway": by_gateway, "failure_reasons": failure_reasons}


@frappe.whitelist()
def get_overdue_aging(now: str | None = None) -> dict:
	"""Outstanding Open/Overdue invoices bucketed by days overdue."""
	require_operator()
	today = frappe.utils.getdate(now)
	buckets = {label: {"count": 0, "amount": 0.0} for label, _lo, _hi in AGING_BUCKETS}
	for inv in frappe.get_all(
		"Invoice",
		filters=[["status", "in", ["Open", "Overdue"]], ["invoice_type", "=", "Billable"]],
		fields=["total", "amount_paid", "due_date"],
	):
		if not inv.due_date:
			continue
		days = (today - frappe.utils.getdate(inv.due_date)).days
		if days < 0:
			continue
		due = frappe.utils.flt(inv.total) - frappe.utils.flt(inv.amount_paid)
		for label, lo, hi in AGING_BUCKETS:
			if lo <= days <= hi:
				buckets[label]["count"] += 1
				buckets[label]["amount"] = frappe.utils.flt(buckets[label]["amount"] + due, 2)
				break
	return buckets


@frappe.whitelist()
def get_free_trial_costs(from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Free/trial subsidy (true cost) — cost_report invoices by cluster and plan."""
	require_operator()
	invoices = frappe.get_all(
		"Invoice",
		filters=[["invoice_type", "=", "Cost Report"]] + _period_filter("period_start", from_date, to_date),
		fields=["name", "subtotal"],
	)
	total = sum(frappe.utils.flt(i.subtotal) for i in invoices)
	by_cluster, by_plan = {}, {}
	if invoices:
		for li in frappe.get_all(
			"Invoice Line Item",
			filters={"parent": ["in", [i.name for i in invoices]]},
			fields=["cluster", "plan", "amount"],
		):
			by_cluster[li.cluster or "global"] = by_cluster.get(li.cluster or "global", 0) + frappe.utils.flt(
				li.amount
			)
			if li.plan:
				by_plan[li.plan] = by_plan.get(li.plan, 0) + frappe.utils.flt(li.amount)
	return {
		"total_subsidy": frappe.utils.flt(total, 2),
		"by_cluster": {k: frappe.utils.flt(v, 2) for k, v in by_cluster.items()},
		"by_plan": {k: frappe.utils.flt(v, 2) for k, v in by_plan.items()},
	}


@frappe.whitelist()
def list_all_invoices(status: str = None, team: str = None, limit: int = 500) -> list[dict]:
	"""Global invoice list (admin) with optional status/team filters — the
	drill-down target for the Collected / Outstanding cards.

	`status` accepts a literal Invoice status (Paid/Open/Overdue/Draft/…) or the
	pseudo-filters `outstanding` (Open+Overdue) and `paid`.
	"""
	require_operator()
	filters = {"invoice_type": "Billable"}
	if team:
		filters["team"] = team
	if status == "outstanding":
		filters["status"] = ["in", ["Open", "Overdue"]]
	elif status == "paid":
		filters["status"] = "Paid"
	elif status:
		filters["status"] = status.title()
	rows = frappe.get_all(
		"Invoice",
		filters=filters,
		fields=[
			"name",
			"team",
			"status",
			"total",
			"amount_paid",
			"currency",
			"period_start",
			"period_end",
			"due_date",
		],
		order_by="period_start desc, team asc",
		limit=limit,
	)
	for r in rows:
		r["outstanding"] = frappe.utils.flt(frappe.utils.flt(r.total) - frappe.utils.flt(r.amount_paid), 2)
	return rows
