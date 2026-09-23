# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Priced whole-CPU server plans within the Team's policy and spending limit."""

import math

import frappe
from frappe import _

from central.billing import authz
from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.catalog.composition import (
	COMPUTE,
	DISK,
	MEMORY,
	composition_quantities,
	parse_vcpu_steps,
)
from central.billing.catalog.entitlements import get_team_caps
from central.billing.catalog.pricing import resolve_component_rate, resolve_rate
from central.billing.catalog.rate_card import COMPONENT_UNITS
from central.billing.catalog.trials import trial_plan_names


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
def get_eligible_plans(
	cluster: str | None = None,
	team: str | None = None,
	exclude_subscription: str | None = None,
	for_resize: int | str | None = None,
) -> dict:
	"""Return priced server plans and custom profiles authorized for this Team.

	Exclude the named subscription from existing spend when comparing resize options.
	Atlas performs placement at creation; this catalog does not promise regional capacity.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	caps = get_team_caps(team)
	spend_cap = frappe.utils.flt(caps.max_spend)
	current_spend = _current_run_rate(team, exclude=exclude_subscription)
	available = max(0.0, frappe.utils.flt(spend_cap - current_spend))
	cluster = (cluster or "").strip() or None

	allowed_plans = _allowlist(caps.allowed_plans)
	allowed_clusters = _allowlist(caps.allowed_clusters)

	# Staging trials: narrow the menu to the plans flagged Available on Trial (none
	# flagged = no extra narrowing) and offer no design-your-own — a trial can't
	# provision a composed server without a full billing profile. Resize is the
	# way off that plan, so it sees the same catalog as a paying team.
	is_staging_trial = bool(frappe.db.get_value("Team", team, "is_staging_trial"))
	resizing = bool(frappe.utils.cint(for_resize))
	if is_staging_trial and not resizing:
		trial_plans = trial_plan_names()
		if trial_plans is not None:
			allowed_plans = trial_plans if allowed_plans is None else (allowed_plans & trial_plans)

	header = {
		"team": team,
		"cluster": cluster,
		"currency": currency,
		"tier": caps.tier,
		"max_spend": spend_cap,
		"current_spend": current_spend,
		"available": available,
		"capacity": {"gated": False, "available": True, "unmeasured": True, "largest_vm": None},
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

	rate_card = {} if is_staging_trial and not resizing else _rate_card(currency, cluster)
	profiles = [] if is_staging_trial and not resizing else _profiles(server_categories)

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
		# Trials aren't tier-gated — spend is bounded by credits + the server cap, not headroom.
		if not is_staging_trial and frappe.utils.flt(rate) > available:
			continue  # would push the team past its remaining trust-tier headroom
		row = _plan_row(p, currency, cluster, rate, includes_by_plan.get(p.name, []))
		if not _has_whole_virtual_cpus(row["includes"]):
			continue

		plans.append(row)

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
	profiles = [
		{
			"sub_category": r.name,
			"ram_ratio": r.ram_ratio,
			"vcpu_steps": [
				step for step in parse_vcpu_steps(r.vcpu_steps) if _is_whole_virtual_cpu_count(step)
			],
			"disk_steps": disk_steps_for(r.disk_min, r.disk_max),
			"disk_min": r.disk_min,
			"disk_max": r.disk_max,
		}
		for r in rows
	]
	return [profile for profile in profiles if profile["vcpu_steps"]]


def _has_whole_virtual_cpus(includes: list[dict]) -> bool:
	return _is_whole_virtual_cpu_count(composition_quantities(includes).get(COMPUTE, 0))


def _is_whole_virtual_cpu_count(value: float) -> bool:
	# Atlas allocates whole vCPUs; rounding would change the resources behind the price.
	return math.isfinite(value) and value > 0 and value == math.floor(value)


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


def _lock_disclosure(team: str, subscription: str, currency: str) -> dict | None:
	"""What this server's rate is, against what the same shape costs today.

	A resize re-prices at current rates (ADR 0010), so a customer holding a rate
	below today's list is about to give it up — including if they resize back to the
	size they are on now. They are entitled to know that before they confirm, not
	after it shows up on a bill.

	Scoped to `team` even though the caller already resolved the subscription from
	a team-scoped read. A rate is tenant data, and a helper that takes a bare
	subscription id and trusts whoever passed it is one stray decorator away from
	handing another tenant's price to anyone who can guess an id — which is how
	this function was first shipped.
	"""
	from central.billing.api.dashboard.spend import list_rate_for
	from central.billing.catalog.subscriptions import active_segments

	segments = active_segments({"name": subscription, "team": team})
	if not segments:
		return None
	segment = segments[0]
	locked = frappe.utils.flt(segment.locked_rate)
	listed = list_rate_for(segment, currency)
	if listed is None or not locked:
		return None
	return {
		"locked_rate": locked,
		"list_rate": frappe.utils.flt(listed),
		"currency": currency,
		# Only a rate BELOW today's list is worth warning about; at or above it there
		# is nothing to lose by re-pricing.
		"gives_up": frappe.utils.flt(listed - locked, 2) if listed > locked else 0.0,
	}


@frappe.whitelist()
def get_composed_config(server: str, team: str | None = None) -> dict:
	"""The config running on `server`, pre-filling the resize slider (#84): its
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
		{"server_id": server, "team": team},
		["name", "pricing_mode", "sub_category", "plan"],
		as_dict=True,
	)
	if not sub:
		return {"resizable": False, "composed": False}

	from central.billing.catalog.composition import COMPUTE, composition_quantities
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
		shape = (
			frappe.db.get_value(
				"Virtual Machine", server, ["vcpus", "memory_megabytes", "disk_gigabytes"], as_dict=True
			)
			or frappe._dict()
		)
		vcpus = shape.vcpus or 0
		memory_gb = (shape.memory_megabytes or 0) / 1024
		disk_gb = shape.disk_gigabytes or 0

	cap = frappe.utils.flt(get_team_caps(team).max_spend)
	return {
		"resizable": True,
		"composed": composed,
		"subscription": sub.name,
		"sub_category": sub.sub_category,
		"plan": sub.plan,  # the current preset, so the picker can pre-select it
		"vcpus": vcpus,
		"memory_gb": memory_gb,
		"disk_gb": disk_gb,
		"available": max(0.0, cap - team_run_rate(team, exclude=sub.name)),
		# What the resize would cost this server in price terms, so the picker can
		# say it before the customer commits rather than after.
		"lock": _lock_disclosure(team, sub.name, _team_currency(team)),
	}


@frappe.whitelist(methods=["POST"])
def resize_composed_config(subscription: str, includes: list | str, sub_category: str | None = None) -> dict:
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

	before = frappe.db.count(
		"Subscription Change", {"subscription": subscription, "change_type": "Plan Changed"}
	)
	resize_composed_subscription(subscription, includes, sub_category)
	after = frappe.db.count(
		"Subscription Change", {"subscription": subscription, "change_type": "Plan Changed"}
	)
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


def _current_run_rate(team: str, exclude: str | None = None) -> float:
	"""The team's committed monthly run-rate: the summed open-segment locked rate of
	its subscriptions, off the Subscription Change ledger (ADR 0010). Counts presets and
	composed configs alike; a team bills in one currency, so the rates are comparable.
	`exclude` drops one subscription — used by resize to free the server's own spend."""
	from central.billing.catalog.subscriptions import team_run_rate

	return team_run_rate(team, exclude=exclude)


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
			{"resource_type": i.resource_type, "quantity": i.quantity, "unit": i.unit} for i in includes
		],
	}
