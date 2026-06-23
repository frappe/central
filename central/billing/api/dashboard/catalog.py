# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Plan catalog for the dashboard's create-server flow.

Lists the active plans a team can actually provision on a given cluster: priced
for the team's currency on that cluster, admitted by the trust tier's allow-lists,
and within the team's *remaining* trust-tier headroom — the spend cap minus what
its already-running resources consume. The cluster's provisioning check still has
the final say at provision time (run-rate vs the live cap, ADR 0006); this read
only narrows the menu the customer is shown.
"""

import frappe

from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.catalog.entitlements import get_team_caps
from central.billing.catalog.pricing import resolve_rate


def _allowlist(value) -> set[str] | None:
	"""A tier allow-list (JSON field) as a set of names, or None for 'no restriction'.

	An empty/unset list is *not* an empty allow-list — it means the tier places no
	restriction on this axis, so every candidate qualifies."""
	if not value:
		return None
	items = frappe.parse_json(value) if isinstance(value, str) else value
	names = {str(x).strip() for x in (items or []) if str(x).strip()}
	return names or None


# Canonical class order for the grouped menu (matches the Plan.plan_class Select).
# An unset class is folded into "General" so unclassified plans get a real label.
_CLASS_ORDER = ["General", "CPU Optimised", "Memory Optimised", "Storage Optimised", "Custom"]


@frappe.whitelist()
def get_eligible_plans(cluster: str | None = None, team: str | None = None) -> dict:
	"""Active plans the team can provision on `cluster`, grouped by plan class.

	`plans` is a `{plan_class: [rows]}` map so the client can render one tab per
	class without re-grouping: keys are in canonical order (`_CLASS_ORDER`, then any
	unknown classes alphabetically), rows within each class are cheapest-first, and
	an unset class is folded into "General". A forbidden cluster yields an empty map.

	A plan is offered only when ALL of the following hold:
	  - it is active;
	  - the tier's `allowed_plans` admits it (unset = all plans);
	  - the tier's `allowed_clusters` admits `cluster` (unset = all clusters);
	  - it prices the team's currency on this cluster (the regional Catalog Rate,
	    else the global blank-cluster rate);
	  - its rate fits the team's *remaining* headroom: the trust-tier spend cap
	    (`max_spend`) minus the run-rate of its already-running resources. A team
	    on a 4000 cap already running 1000 only sees plans priced 3000 or less.
	    An untiered team has a 0 cap and so no headroom.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	caps = get_team_caps(team)
	spend_cap = frappe.utils.flt(caps.max_spend)
	current_spend = _current_run_rate(team)
	available = max(0.0, frappe.utils.flt(spend_cap - current_spend))
	cluster = (cluster or "").strip() or None

	allowed_plans = _allowlist(caps.allowed_plans)
	allowed_clusters = _allowlist(caps.allowed_clusters)

	header = {
		"team": team, "cluster": cluster, "currency": currency, "tier": caps.tier,
		"max_spend": spend_cap, "current_spend": current_spend, "available": available,
	}

	# The tier forbids this cluster outright — nothing is provisionable here.
	if cluster and allowed_clusters is not None and cluster not in allowed_clusters:
		return {**header, "plans": {}}

	# The whole active catalog is wanted on purpose — currency/cluster/headroom
	# filtering happens in Python below — so opt out of pagination explicitly.
	candidates = frappe.get_all(
		"Plan",
		filters={"is_active": 1},
		fields=["name", "title", "plan_class", "billing_cycle"],
		order_by="title asc",
		limit=0,
	)
	if allowed_plans is not None:
		candidates = [p for p in candidates if p.name in allowed_plans]

	# Bulk-load rates + composition for the whole candidate set up front, so the loop
	# below is in-memory work — no per-plan query (was an N+1: a rates query and a
	# get_doc per plan).
	names = [p.name for p in candidates]
	rates_by_plan = _rates_by_plan(names)
	includes_by_plan = _includes_by_plan(names)

	plans = []
	for p in candidates:
		rate = resolve_rate(rates_by_plan.get(p.name, []), currency, cluster)
		if rate is None:
			continue  # not priced for this currency/cluster → not available here
		if frappe.utils.flt(rate) > available:
			continue  # would push the team past its remaining trust-tier headroom
		plans.append(_plan_row(p, currency, cluster, rate, includes_by_plan.get(p.name, [])))

	# Cheapest first; the title-ordered iteration above is a stable tiebreaker.
	plans.sort(key=lambda p: frappe.utils.flt(p["rate"]))
	return {**header, "plans": _group_by_class(plans)}


def _rates_by_plan(names: list[str]) -> dict[str, list]:
	"""Every Plan's `Catalog Rate` rows in one query, grouped by plan name."""
	if not names:
		return {}
	grouped: dict[str, list] = {}
	for r in frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": "Plan", "priced_for": ["in", names]},
		fields=["priced_for", "cluster", "currency", "rate"],
	):
		grouped.setdefault(r.priced_for, []).append(r)
	return grouped


def _includes_by_plan(names: list[str]) -> dict[str, list]:
	"""Every Plan's `Plan Includes` rows in one query, grouped by parent (in `idx` order)."""
	if not names:
		return {}
	grouped: dict[str, list] = {}
	for r in frappe.get_all(
		"Plan Includes",
		filters={"parenttype": "Plan", "parent": ["in", names]},
		fields=["parent", "resource_type", "quantity", "unit"],
		order_by="idx asc",
	):
		grouped.setdefault(r.parent, []).append(r)
	return grouped


def _group_by_class(rows: list[dict]) -> dict[str, list]:
	"""Group plan rows by class into a `{plan_class: [rows]}` map. Keys are emitted in
	canonical order (then any unknown classes, alphabetically); `rows` keeps the
	caller's order within each class (so cheapest-first survives)."""
	grouped: dict[str, list] = {}
	for row in rows:
		grouped.setdefault(row["plan_class"], []).append(row)
	known = [c for c in _CLASS_ORDER if c in grouped]
	extra = sorted(c for c in grouped if c not in _CLASS_ORDER)
	return {c: grouped[c] for c in [*known, *extra]}


def _current_run_rate(team: str) -> float:
	"""The team's committed monthly run-rate: the summed `locked_rate` of its active
	price-locks. A team bills in one currency, so the locks are already in it — no
	normalisation needed (unlike the cross-team, INR-normalised admin view)."""
	rates = frappe.get_all(
		"Price Lock",
		filters={"team": team, "ended_at": ["is", "not set"]},
		pluck="locked_rate",
	)
	return frappe.utils.flt(sum(frappe.utils.flt(r) for r in rates))


def _plan_row(plan, currency: str, cluster: str | None, rate, includes) -> dict:
	"""A create-server menu entry: identity, composition (specs), and resolved rate.
	`plan` is a bulk-fetched Plan row; `includes` its pre-loaded Plan Includes rows."""
	return {
		"plan": plan.name,
		"title": plan.title,
		"plan_class": plan.plan_class or "General",  # unset class groups under General
		"billing_cycle": plan.billing_cycle,
		"currency": currency,
		"cluster": cluster,
		"rate": frappe.utils.flt(rate),
		"includes": [
			{"resource_type": i.resource_type, "quantity": i.quantity, "unit": i.unit}
			for i in includes
		],
	}
