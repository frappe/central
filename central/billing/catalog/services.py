# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Read models for team-level metered services (ADR 0013/0015).

A team-level service (AI tokens, email, common PDF, snapshot storage) is a Plan whose
family is not provisioned as a whole Server. These readers back both the pilot-facing
in-app flow (`api/billing_api.py`) and the admin billing console (`api/admin`): what
services a team can subscribe to, and what it currently runs.
"""

import frappe

from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


def list_service_plans(currency: str, cluster: str | None = None) -> list[dict]:
	"""Active team-level service plans, priced for `currency` on `cluster`.

	One entry per active Plan under a non-Server family, carrying its billing shape
	(Fixed bundle vs Metered), the family's settlement + reporting mode, the included
	allowance, and the resolved rate (a bundle's flat price, or a metered per-unit rate).
	`rate` is None when the family has no rate for this currency/cluster."""
	service_categories = {
		c.name: c
		for c in frappe.get_all(
			"Plan Category",
			filters={"is_active": 1, "provision_target": ["!=", "Server"]},
			fields=["name", "billing_type", "settlement_mode", "reporting_mode"],
		)
	}
	if not service_categories:
		return []

	plans = frappe.get_all(
		"Plan",
		filters={"category": ["in", list(service_categories)], "is_active": 1},
		fields=["name", "title", "category"],
	)
	includes = _includes_by_plan([p.name for p in plans])

	out = []
	for p in plans:
		cat = service_categories[p.category]
		inc = includes.get(p.name)
		rate = resolve_rate(get_catalog_rates("Plan", p.name), currency, cluster)
		out.append(
			{
				"plan": p.name,
				"title": p.title,
				"category": p.category,
				"billing_type": cat.billing_type,
				"settlement_mode": cat.settlement_mode or "Postpaid Overage",
				"reporting_mode": cat.reporting_mode or "Authoritative",
				"resource_type": inc.resource_type if inc else None,
				"unit": inc.unit if inc else None,
				"allowance": frappe.utils.flt(inc.quantity) if inc else 0.0,
				"rate": frappe.utils.flt(rate) if rate is not None else None,
				"currency": currency,
			}
		)
	return out


def team_service_subscriptions(team: str) -> list[dict]:
	"""A team's active team-level service subscriptions (ADR 0013): one per synthesized
	subject, with its plan, cluster, locked rate, family modes, included allowance, and
	the current period's reported usage. The console's view of a team's metered footprint."""
	from central.billing.catalog.subscriptions import team_active_segments

	segs = [s for s in team_active_segments(team) if s.service_subject]
	if not segs:
		return []

	includes = _includes_by_plan([s.plan for s in segs if s.plan])
	modes = _category_modes_by_plan([s.plan for s in segs if s.plan])

	out = []
	for s in segs:
		inc = includes.get(s.plan)
		mode = modes.get(s.plan, {})
		out.append(
			{
				"subscription": s.subscription,
				"service_subject": s.service_subject,
				"plan": s.plan,
				"title": frappe.db.get_value("Plan", s.plan, "title") if s.plan else None,
				"cluster": s.cluster,
				"currency": s.currency,
				"locked_rate": s.locked_rate,
				"billing_type": mode.get("billing_type"),
				"settlement_mode": mode.get("settlement_mode") or "Postpaid Overage",
				"reporting_mode": mode.get("reporting_mode") or "Authoritative",
				"resource_type": inc.resource_type if inc else None,
				"unit": inc.unit if inc else None,
				"allowance": frappe.utils.flt(inc.quantity) if inc else 0.0,
				"period_usage": _current_period_usage(s.service_subject),
			}
		)
	return out


def _includes_by_plan(plan_names: list[str]) -> dict:
	"""The single include row (resource_type, quantity, unit) per plan, in one query.
	A team-level service plan is single-resource (ADR 0008), so at most one row matters."""
	names = [n for n in set(plan_names) if n]
	if not names:
		return {}
	by_plan: dict = {}
	for row in frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": ["in", names]},
		fields=["parent", "resource_type", "quantity", "unit"],
	):
		by_plan.setdefault(row.parent, row)  # first (single) row per plan
	return by_plan


def _category_modes_by_plan(plan_names: list[str]) -> dict:
	"""Plan -> its family's billing_type + settlement/reporting mode, in two queries."""
	names = [n for n in set(plan_names) if n]
	if not names:
		return {}
	plan_cat = {
		p.name: p.category
		for p in frappe.get_all("Plan", filters={"name": ["in", names]}, fields=["name", "category"])
	}
	cats = {
		c.name: c
		for c in frappe.get_all(
			"Plan Category",
			filters={"name": ["in", list(set(plan_cat.values()))]},
			fields=["name", "billing_type", "settlement_mode", "reporting_mode"],
		)
	}
	return {plan: cats.get(cat, frappe._dict()) for plan, cat in plan_cat.items()}


def _current_period_usage(subject: str) -> float:
	"""The reported usage for a subject in the current billing month (summed across its
	rollup rows, though there is normally one per meter). A quick read for the console —
	billing itself measures overage against the locked allowance at invoice time."""
	month_start = frappe.utils.get_first_day(frappe.utils.nowdate())
	rows = frappe.get_all(
		"Usage Rollup",
		filters={"resource_id": subject, "period_start": [">=", month_start]},
		pluck="quantity",
	)
	return frappe.utils.flt(sum(frappe.utils.flt(q) for q in rows))
