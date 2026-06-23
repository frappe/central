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
from central.billing.catalog.pricing import get_catalog_rates, resolve_rate


def _allowlist(value) -> set[str] | None:
	"""A tier allow-list (JSON field) as a set of names, or None for 'no restriction'.

	An empty/unset list is *not* an empty allow-list — it means the tier places no
	restriction on this axis, so every candidate qualifies."""
	if not value:
		return None
	items = frappe.parse_json(value) if isinstance(value, str) else value
	names = {str(x).strip() for x in (items or []) if str(x).strip()}
	return names or None


@frappe.whitelist()
def get_eligible_plans(cluster: str | None = None, team: str | None = None) -> dict:
	"""Active plans the team can provision on `cluster`, filtered by its trust tier.

	A plan is offered only when ALL of the following hold:
	  - it is active;
	  - the tier's `allowed_plans` admits it (unset = all plans);
	  - the tier's `allowed_clusters` admits `cluster` (unset = all clusters) —
	    a forbidden cluster yields an empty list;
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
		return {**header, "plans": []}

	plans = []
	for name in frappe.get_all("Plan", filters={"is_active": 1}, pluck="name", order_by="title asc"):
		if allowed_plans is not None and name not in allowed_plans:
			continue
		rate = resolve_rate(get_catalog_rates("Plan", name), currency, cluster)
		if rate is None:
			continue  # not priced for this currency/cluster → not available here
		if frappe.utils.flt(rate) > available:
			continue  # would push the team past its remaining trust-tier headroom
		plans.append(_plan_row(name, currency, cluster, rate))

	# Cheapest first; the title-ordered iteration above is a stable tiebreaker.
	plans.sort(key=lambda p: frappe.utils.flt(p["rate"]))
	return {**header, "plans": plans}


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


def _plan_row(name: str, currency: str, cluster: str | None, rate) -> dict:
	"""A create-server menu entry: identity, composition (specs), and resolved rate."""
	doc = frappe.get_doc("Plan", name)
	return {
		"plan": name,
		"title": doc.title,
		"plan_class": doc.plan_class,
		"billing_cycle": doc.billing_cycle,
		"currency": currency,
		"cluster": cluster,
		"rate": frappe.utils.flt(rate),
		"includes": [
			{"resource_type": i.resource_type, "quantity": i.quantity, "unit": i.unit}
			for i in doc.includes
		],
	}
