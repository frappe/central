# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog + consumption admin views: product/cluster catalog, plan-rate edits,
cluster/plan run-rate consumption, and trial→paid conversion analysis.
"""

import frappe
from frappe import _

from central.billing.authz import require_operator
from central.billing.api.admin._shared import _active_locks, _plan_monthly_inr, _to_inr


@frappe.whitelist()
def get_catalog() -> dict:
	"""Products & infrastructure: plans (with INR base rate) and the clusters teams
	run in (with active resource counts). Metered overage plans are Plans too now
	(ADR 0008), so they appear in the plan list rather than a separate add-on list."""
	require_operator()
	plans = []
	for p in frappe.get_all("Plan", fields=["name", "title", "billing_cycle", "is_active"], order_by="name asc"):
		plans.append({
			**p,
			"inr_rate": _plan_monthly_inr(p.name, None),
			"active_resources": frappe.db.count("Price Lock", {"plan": p.name, "ended_at": ["is", "not set"]}),
		})
	clusters = {}
	for lock in _active_locks():
		c = clusters.setdefault(lock.cluster or "global", {"cluster": lock.cluster or "global", "resources": 0, "teams": set()})
		c["resources"] += 1
		c["teams"].add(lock.team)
	cluster_rows = sorted(
		({"cluster": c["cluster"], "resources": c["resources"], "teams": len(c["teams"])} for c in clusters.values()),
		key=lambda r: r["resources"], reverse=True,
	)
	return {"plans": plans, "clusters": cluster_rows}


@frappe.whitelist()
def update_plan_rate(plan: str, currency: str, rate: int, cluster: str = "") -> dict:
	"""Price management: change a plan's Catalog Rate. Existing price-locks are
	untouched (they copied the rate at provision) — only new provisions lock the
	new rate. Zero new plans."""
	require_operator()
	if not frappe.db.exists("Plan", plan):
		frappe.throw(f"Plan {plan!r} does not exist.")
	cluster = cluster or None

	existing = frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": "Plan", "priced_for": plan, "currency": currency},
		fields=["name", "cluster"],
	)
	match = next((r for r in existing if (r.cluster or None) == cluster), None)
	if match:
		frappe.db.set_value("Catalog Rate", match.name, "rate", rate)
	else:
		frappe.get_doc(
			{
				"doctype": "Catalog Rate",
				"priced_doctype": "Plan",
				"priced_for": plan,
				"currency": currency,
				"cluster": cluster,
				"rate": rate,
			}
		).insert(ignore_permissions=True)
	return {"plan": plan, "currency": currency, "cluster": cluster or "global", "rate": frappe.utils.flt(rate)}


@frappe.whitelist()
def update_component_rate(resource_type: str, currency: str, rate: int, cluster: str = "") -> dict:
	"""Price management for the composed-config rate card (ADR 0009): set one
	`Resource Type`'s per-unit `Catalog Rate`. Like `update_plan_rate`, it is a
	single document edit — it mints no plans, and a running composed config keeps
	billing its locked config rate (only a new provision/resize picks up the new
	rate, #80/#82)."""
	require_operator()
	from central.billing.catalog.pricing import set_catalog_rate

	if not frappe.db.exists("Resource Type", resource_type):
		frappe.throw(_("Resource Type {0} does not exist.").format(frappe.bold(resource_type)))
	cluster = cluster or None
	set_catalog_rate("Resource Type", resource_type, currency, rate, cluster=cluster)
	return {
		"resource_type": resource_type,
		"currency": currency,
		"cluster": cluster or "global",
		"rate": frappe.utils.flt(rate),
	}


@frappe.whitelist()
def get_cluster_consumption() -> list[dict]:
	"""Cluster-wise resource consumption (active price-locks) + monthly run-rate.

	Run-rate is normalised to INR (via each plan's INR catalog rate) so regions
	billed in EUR/USD are comparable on one axis.
	"""
	require_operator()
	out = {}
	for lock in _active_locks():
		c = out.setdefault(lock.cluster or "global", {"cluster": lock.cluster or "global", "resources": 0, "monthly": 0.0, "currency": "INR"})
		c["resources"] += 1
		c["monthly"] = frappe.utils.flt(c["monthly"] + _plan_monthly_inr(lock.plan, lock.cluster), 2)
	return sorted(out.values(), key=lambda r: r["monthly"], reverse=True)


@frappe.whitelist()
def get_plan_consumption() -> list[dict]:
	"""Plan-wise consumption analysis (INR-normalised monthly run-rate)."""
	require_operator()
	out = {}
	for lock in _active_locks():
		p = out.setdefault(lock.plan or "—", {"plan": lock.plan or "—", "resources": 0, "monthly": 0.0, "currency": "INR"})
		p["resources"] += 1
		p["monthly"] = frappe.utils.flt(p["monthly"] + _plan_monthly_inr(lock.plan, lock.cluster), 2)
	return sorted(out.values(), key=lambda r: r["monthly"], reverse=True)


@frappe.whitelist()
def get_conversion() -> dict:
	"""Trial → paid conversion."""
	require_operator()
	from central.billing.catalog.trials import entry_tier

	entry = entry_tier()
	tiers = frappe.get_all(
		"Billing Profile",
		filters={"trust_tier": ["is", "set"]},
		fields=["team", "trust_tier as tier", "promotion_basis"],
	)
	total = len(tiers)
	trial = sum(1 for t in tiers if t.tier == entry)
	paid = total - trial
	converted = sum(1 for t in tiers if (t.promotion_basis or "").startswith("converted"))
	return {"total_teams": total, "trial": trial, "paid": paid, "converted": converted,
			"conversion_rate": round(paid / total, 3) if total else 0}


@frappe.whitelist()
def get_trial_detail() -> dict:
	"""Trial subsidy analysis with full provenance: how many teams are still on
	trial, the per-team subsidy, and the exact cost_report invoices the total is
	summed from (so 'where does ₹X come from?' is answerable)."""
	require_operator()
	from central.billing.catalog.trials import entry_tier

	entry = entry_tier()
	invoices = frappe.get_all(
		"Invoice", filters={"invoice_type": "Cost Report"},
		fields=["name", "team", "subtotal", "currency", "period_start", "period_end"],
		order_by="period_start desc",
	)
	by_team = {}
	still_on_trial, converted_subsidy, trial_subsidy = 0.0, 0.0, 0.0
	for inv in invoices:
		tier = frappe.db.get_value("Billing Profile", inv.team, "trust_tier")
		on_trial = tier == entry
		inr = _to_inr(inv.subtotal, inv.currency)
		t = by_team.setdefault(inv.team, {"team": inv.team, "on_trial": on_trial, "tier": tier or "—",
											"subsidy": 0.0, "currency": inv.currency, "invoices": []})
		t["subsidy"] = frappe.utils.flt(t["subsidy"] + frappe.utils.flt(inv.subtotal), 2)
		t["invoices"].append({"name": inv.name, "subtotal": frappe.utils.flt(inv.subtotal, 2),
							   "period_start": str(inv.period_start), "period_end": str(inv.period_end)})
		if on_trial:
			trial_subsidy += inr
		else:
			converted_subsidy += inr
	teams = sorted(by_team.values(), key=lambda r: r["subsidy"], reverse=True)
	return {
		"entry_tier": entry,
		"still_on_trial": sum(1 for t in teams if t["on_trial"]),
		"converted": sum(1 for t in teams if not t["on_trial"]),
		"trial_subsidy_inr": frappe.utils.flt(trial_subsidy, 2),
		"converted_subsidy_inr": frappe.utils.flt(converted_subsidy, 2),
		"total_subsidy_inr": frappe.utils.flt(trial_subsidy + converted_subsidy, 2),
		"teams": teams,
	}


@frappe.whitelist()
def get_trial_costs_detail() -> dict:
	"""Trial subsidy split: still-on-trial (unconverted) vs converted-to-paid."""
	require_operator()
	from central.billing.catalog.trials import entry_tier

	entry = entry_tier()
	unconverted, converted = 0.0, 0.0
	for inv in frappe.get_all("Invoice", filters={"invoice_type": "Cost Report"}, fields=["team", "subtotal"]):
		tier = frappe.db.get_value("Billing Profile", inv.team, "trust_tier")
		if tier == entry:
			unconverted += frappe.utils.flt(inv.subtotal)
		else:
			converted += frappe.utils.flt(inv.subtotal)
	return {"unconverted_subsidy": frappe.utils.flt(unconverted, 2),
			"converted_cost": frappe.utils.flt(converted, 2),
			"total": frappe.utils.flt(unconverted + converted, 2)}
