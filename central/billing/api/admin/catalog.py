# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Catalog + consumption admin views: product/cluster catalog, plan-rate edits,
cluster/plan run-rate consumption, and trial→paid conversion analysis.
"""

import frappe

from central.billing.authz import require_operator
from central.billing.api.admin._shared import _active_segments, _plan_monthly_inr, _to_inr


@frappe.whitelist()
def get_catalog() -> dict:
	"""Products & infrastructure: plans (with INR base rate) and the clusters teams
	run in (with active resource counts). Metered overage plans are Plans too now
	(ADR 0008), so they appear in the plan list rather than a separate add-on list."""
	require_operator()
	# One ledger sweep, counted per plan/cluster in Python — no query per plan.
	segments = _active_segments()
	resources_by_plan: dict = {}
	for seg in segments:
		resources_by_plan[seg.plan] = resources_by_plan.get(seg.plan, 0) + 1
	plans = []
	for p in frappe.get_all("Plan", fields=["name", "title", "billing_cycle", "is_active"], order_by="name asc"):
		plans.append({
			**p,
			"inr_rate": _plan_monthly_inr(p.name, None),
			"active_resources": resources_by_plan.get(p.name, 0),
		})
	clusters = {}
	for seg in segments:
		c = clusters.setdefault(seg.cluster or "global", {"cluster": seg.cluster or "global", "resources": 0, "teams": set()})
		c["resources"] += 1
		c["teams"].add(seg.team)
	cluster_rows = sorted(
		({"cluster": c["cluster"], "resources": c["resources"], "teams": len(c["teams"])} for c in clusters.values()),
		key=lambda r: r["resources"], reverse=True,
	)
	return {"plans": plans, "clusters": cluster_rows}


@frappe.whitelist(methods=["POST"])
def create_configured_plan(title: str, vcpu: float, ratio: str = "1:2", disk_gb: float = 0,
						   memory_gb: float | None = None, billing_cycle: str = "Monthly",
						   category: str = "VM Plans", sub_category: str | None = None) -> dict:
	"""Author a bundle Plan from configurator inputs — operator only. The one HTTP
	door to `plans.create_configured_plan`; the primitive itself is not whitelisted."""
	require_operator()
	from central.billing.catalog import plans

	name = plans.create_configured_plan(
		title, vcpu, ratio=ratio, disk_gb=disk_gb, memory_gb=memory_gb,
		billing_cycle=billing_cycle, category=category, sub_category=sub_category)
	return {"plan": name}


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


def update_component_rate(resource_type: str, currency: str, rate: int, cluster: str = "") -> dict:
	"""Set one `Resource Type`'s per-unit `Catalog Rate` (the composed-config rate card).

	No longer a whitelisted public endpoint (ADR 0011): the Plan Configurator is the
	single authoring authority, so the component card is written through its internal
	path (`component_card.set_component_rate`). This thin wrapper stays for migrations
	and tests; it delegates to that single write so there is one place a component rate
	is set."""
	from central.billing.catalog.component_card import set_component_rate

	return set_component_rate(resource_type, currency, rate, cluster=cluster or None)


@frappe.whitelist()
def get_cluster_consumption() -> list[dict]:
	"""Cluster-wise resource consumption (active price-locks) + monthly run-rate.

	Run-rate is normalised to INR (via each plan's INR catalog rate) so regions
	billed in INR/USD are comparable on one axis.
	"""
	require_operator()
	out = {}
	for seg in _active_segments():
		c = out.setdefault(seg.cluster or "global", {"cluster": seg.cluster or "global", "resources": 0, "monthly": 0.0, "currency": "INR"})
		c["resources"] += 1
		c["monthly"] = frappe.utils.flt(c["monthly"] + _segment_monthly_inr(seg), 2)
	return sorted(out.values(), key=lambda r: r["monthly"], reverse=True)


@frappe.whitelist()
def get_plan_consumption() -> list[dict]:
	"""Plan-wise consumption analysis (INR-normalised monthly run-rate)."""
	require_operator()
	out = {}
	for seg in _active_segments():
		key = seg.plan or "Custom"
		p = out.setdefault(key, {"plan": key, "resources": 0, "monthly": 0.0, "currency": "INR"})
		p["resources"] += 1
		p["monthly"] = frappe.utils.flt(p["monthly"] + _segment_monthly_inr(seg), 2)
	return sorted(out.values(), key=lambda r: r["monthly"], reverse=True)


def _segment_monthly_inr(seg) -> float:
	"""A segment's monthly run-rate in INR. A preset resolves its Plan's current INR
	catalog rate (as the old Price Lock aggregate did); a composed config has no Plan,
	so its locked config-total is converted from the segment's currency (#86)."""
	if seg.plan:
		return _plan_monthly_inr(seg.plan, seg.cluster)
	return _to_inr(seg.locked_rate, seg.currency)


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
