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
from frappe import _

from central.billing import authz
from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.catalog.composition import parse_vcpu_steps
from central.billing.catalog.entitlements import get_team_caps
from central.billing.catalog.pricing import resolve_component_rate, resolve_rate
from central.billing.catalog.rate_card import COMPONENT_UNITS


def _allowlist(value) -> set[str] | None:
	"""A tier allow-list (JSON field) as a set of names, or None for 'no restriction'.

	An empty/unset list is *not* an empty allow-list — it means the tier places no
	restriction on this axis, so every candidate qualifies."""
	if not value:
		return None
	items = frappe.parse_json(value) if isinstance(value, str) else value
	names = {str(x).strip() for x in (items or []) if str(x).strip()}
	return names or None


# Canonical order for the grouped menu (the VM Plans optimisation profiles, the
# Plan Sub-Category masters under that category). An unset sub-category is folded
# into "General" so unclassified plans still get a real label.
_SUB_CATEGORY_ORDER = ["General", "CPU Optimised", "Memory Optimised", "Storage Optimised", "Custom"]


@frappe.whitelist()
def get_eligible_plans(cluster: str | None = None, team: str | None = None) -> dict:
	"""Active plans the team can provision on `cluster`, grouped by sub-category.

	`plans` is a `{sub_category: [rows]}` map so the client can render one tab per
	sub-category without re-grouping: keys are in canonical order (`_SUB_CATEGORY_ORDER`,
	then any unknown sub-categories alphabetically), rows within each are cheapest-first,
	and an unset sub-category is folded into "General". A forbidden cluster yields an empty map.

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
	# A "design your own" config needs the same three things the slider does: the
	# per-resource rate card, the profile bounds, and the headroom ceiling (#83).
	empty = {**header, "plans": {}, "rate_card": {}, "profiles": []}

	# The tier forbids this cluster outright — nothing is provisionable here, and the
	# rate card / profiles come back empty too (no composed configs offered either).
	if cluster and allowed_clusters is not None and cluster not in allowed_clusters:
		return empty

	# Only families that provision a server belong in the create-server menu — AI
	# Tokens, storage subscriptions, etc. are billable but not provisioned here. The
	# family declares this via Plan Category.provision_target (ADR 0007); no server
	# category means nothing is provisionable.
	server_categories = frappe.get_all(
		"Plan Category", filters={"provision_target": "Server"}, pluck="name", limit=0
	)
	if not server_categories:
		return empty

	rate_card = _rate_card(currency, cluster)
	profiles = _profiles(server_categories)

	# The whole active catalog (in server families) is wanted on purpose —
	# currency/cluster/headroom filtering happens in Python below — so opt out of
	# pagination explicitly.
	candidates = frappe.get_all(
		"Plan",
		filters={"is_active": 1, "category": ["in", server_categories]},
		fields=["name", "title", "sub_category", "billing_cycle"],
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
	return {**header, "plans": _group_by_sub_category(plans), "rate_card": rate_card, "profiles": profiles}


def _rate_card(currency: str, cluster: str | None) -> dict:
	"""The composed-config component rate card for the team's currency + region (#79):
	`{resource_type: {rate, unit}}`. Resolved regional-over-global. A currency missing
	*any* component yields an empty card — composed configs aren't offered (not zeros)."""
	card = {}
	for resource_type, unit in COMPONENT_UNITS.items():
		rate = resolve_component_rate(resource_type, currency, cluster)
		if rate is None:
			return {}
		card[resource_type] = {"rate": frappe.utils.flt(rate), "unit": unit}
	return card


def _profiles(server_categories: list[str]) -> list[dict]:
	"""The optimisation profiles (#81) the slider bounds itself with: ratio, the
	allowed vCPU steps, and the storage ladder (the disk rungs within [min, max]),
	per active compute Plan Sub-Category."""
	from central.billing.catalog.composition import disk_steps_for

	rows = frappe.get_all(
		"Plan Sub-Category",
		filters={"category": ["in", server_categories], "is_active": 1, "ram_ratio": [">", 0]},
		fields=["name", "ram_ratio", "vcpu_steps", "disk_min", "disk_max"],
		order_by="name asc",
		limit=0,
	)
	return [
		{
			"sub_category": r.name,
			"ram_ratio": r.ram_ratio,
			"vcpu_steps": parse_vcpu_steps(r.vcpu_steps),
			"disk_steps": disk_steps_for(r.disk_min, r.disk_max),
			"disk_min": r.disk_min,
			"disk_max": r.disk_max,
		}
		for r in rows
	]


@frappe.whitelist(methods=["POST"])
def provision_composed_config(
	includes: list | str, sub_category: str, cluster: str, team: str | None = None
) -> dict:
	"""Provision a design-your-own config from the slider (#84). The server is the
	gate: it re-validates composition, ratio, steps, bounds (#81) and that the config
	fits current headroom (#83) before anything is created — a request that slips past
	the client is still refused here."""
	team = _resolve_team(team, require=authz.MANAGE)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	from central.billing.catalog.subscriptions import provision_composed_subscription

	return provision_composed_subscription(team, cluster, includes, sub_category)


@frappe.whitelist()
def get_composed_config(asset: str, team: str | None = None) -> dict:
	"""The config running on `asset`, pre-filling the resize slider (#84): its
	subscription, current shape, and the resize headroom — the cap minus the team's
	*other* run-rate, so the running config's own spend is available to it.

	Works for both a composed server (its exact composition + optimisation profile)
	and a preset one, whose shape is read off the mirrored VM; resizing a preset
	slides it onto a custom config, so `sub_category` is None and the slider defaults
	to the region's first profile. `{resizable: False}` when there's no live
	subscription to resize."""
	team = _resolve_team(team)
	sub = frappe.db.get_value(
		"Subscription",
		{"asset_id": asset, "team": team},
		["name", "pricing_mode", "sub_category"],
		as_dict=True,
	)
	if not sub:
		return {"resizable": False, "composed": False}

	from central.billing.catalog.composition import COMPUTE, DISK, MEMORY, composition_quantities
	from central.billing.catalog.subscriptions import team_run_rate

	composed = sub.pricing_mode == "Composed"
	if composed:
		includes = frappe.get_all(
			"Plan Includes",
			filters={"parenttype": "Subscription", "parent": sub.name},
			fields=["resource_type", "quantity"],
		)
		qty = composition_quantities(includes)
		vcpus, memory_gb, disk_gb = qty.get(COMPUTE, 0), qty.get(MEMORY, 0), qty.get(DISK, 0)
	else:
		# A preset carries no composition — its shape lives on the mirrored VM.
		shape = frappe.db.get_value(
			"Asset", asset, ["vcpus", "memory_megabytes", "disk_gigabytes"], as_dict=True
		) or frappe._dict()
		vcpus = shape.vcpus or 0
		memory_gb = (shape.memory_megabytes or 0) / 1024
		disk_gb = shape.disk_gigabytes or 0

	cap = frappe.utils.flt(get_team_caps(team).max_spend)
	return {
		"resizable": True,
		"composed": composed,
		"subscription": sub.name,
		"sub_category": sub.sub_category,
		"vcpus": vcpus,
		"memory_gb": memory_gb,
		"disk_gb": disk_gb,
		"available": max(0.0, cap - team_run_rate(team, exclude=sub.name)),
	}


@frappe.whitelist(methods=["POST"])
def resize_composed_config(
	subscription: str, includes: list | str, sub_category: str | None = None
) -> dict:
	"""Resize a running config from the slider (#84) — the changed-event re-lock (#82).
	Re-validates the new shape + headroom server-side before re-locking at the current
	rate card. Returns whether a new segment was opened (a no-op resize returns False)."""
	team = frappe.db.get_value("Subscription", subscription, "team")
	if not team:
		frappe.throw(_("Unknown subscription {0}.").format(frappe.bold(subscription)))
	authz.require_capability(team, authz.MANAGE)
	if isinstance(includes, str):
		includes = frappe.parse_json(includes)
	from central.billing.catalog.subscriptions import resize_composed_subscription

	before = frappe.db.count("Subscription Change", {"subscription": subscription, "change_type": "Plan Changed"})
	resize_composed_subscription(subscription, includes, sub_category)
	after = frappe.db.count("Subscription Change", {"subscription": subscription, "change_type": "Plan Changed"})
	return {"subscription": subscription, "resized": after > before}


def _rates_by_plan(names: list[str]) -> dict[str, list]:
	"""Every Plan's `Catalog Rate` rows in one query, grouped by plan name."""
	if not names:
		return {}
	grouped: dict[str, list] = {}
	for r in frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": "Plan", "priced_for": ["in", names]},
		fields=["priced_for", "cluster", "currency", "rate"],
		limit=0,  # all rates for the candidate set (get_all is unbounded, but be explicit)
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
		limit=0,  # every composition row for the candidate set, not a 20-row page
	):
		grouped.setdefault(r.parent, []).append(r)
	return grouped


def _group_by_sub_category(rows: list[dict]) -> dict[str, list]:
	"""Group plan rows by sub-category into a `{sub_category: [rows]}` map. Keys are
	emitted in canonical order (then any unknown sub-categories, alphabetically); `rows`
	keeps the caller's order within each group (so cheapest-first survives)."""
	grouped: dict[str, list] = {}
	for row in rows:
		grouped.setdefault(row["sub_category"], []).append(row)
	known = [c for c in _SUB_CATEGORY_ORDER if c in grouped]
	extra = sorted(c for c in grouped if c not in _SUB_CATEGORY_ORDER)
	return {c: grouped[c] for c in [*known, *extra]}


def _current_run_rate(team: str) -> float:
	"""The team's committed monthly run-rate: the summed open-segment locked rate of
	its subscriptions, off the Subscription Change ledger (ADR 0010). Counts presets and
	composed configs alike; a team bills in one currency, so the rates are comparable."""
	from central.billing.catalog.subscriptions import team_run_rate

	return team_run_rate(team)


def _plan_row(plan, currency: str, cluster: str | None, rate, includes) -> dict:
	"""A create-server menu entry: identity, composition (specs), and resolved rate.
	`plan` is a bulk-fetched Plan row; `includes` its pre-loaded Plan Includes rows."""
	return {
		"plan": plan.name,
		"title": plan.title,
		"sub_category": plan.sub_category or "General",  # unset sub-category groups under General
		"billing_cycle": plan.billing_cycle,
		"currency": currency,
		"cluster": cluster,
		"rate": frappe.utils.flt(rate),
		"includes": [
			{"resource_type": i.resource_type, "quantity": i.quantity, "unit": i.unit}
			for i in includes
		],
	}
