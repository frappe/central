# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What the team is paying for this cycle, and where its price is held below list.

Two reads behind the reworked Overview. Both are deliberately derived from the same
places billing itself reads — the projection engine for money, the `Subscription
Change` ledger for what is running (ADR 0010) — so a customer never sees a number
the monthly run would disagree with.
"""

import frappe

from central.billing.api.dashboard._shared import _resolve_team, _team_currency
from central.billing.catalog.subscriptions import team_active_segments


@frappe.whitelist()
def get_cycle_costs(team: str | None = None) -> dict:
	"""Everything being billed this cycle, with its month-to-date cost.

	Servers and team-level metered services in one list, because a customer asking
	"what am I paying for" does not care that one has an Asset behind it and the
	other is a synthesized subject (ADR 0013).
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)
	today = frappe.utils.getdate()

	lines = _projected_lines(team, today)
	usage = _metered_usage(team)
	segments = {s.resource_id: s for s in team_active_segments(team) if s.resource_id}

	items = []
	for resource_id, cost in _cost_by_resource(lines).items():
		segment = segments.get(resource_id)
		items.append(
			{
				"resource_id": resource_id,
				"title": _title_for(resource_id, segment),
				"plan": segment.plan if segment else None,
				"cluster": segment.cluster if segment else None,
				"is_service": bool(segment and segment.service_subject),
				"amount": cost,
				"currency": currency,
				# Present only for a metered subject, and only where the plan bundles
				# an allowance — a draw-down bar is meaningless without a ceiling.
				"usage": usage.get(resource_id),
			}
		)

	items.sort(key=lambda i: i["amount"], reverse=True)
	return {"currency": currency, "items": items, "total": frappe.utils.flt(sum(i["amount"] for i in items), 2)}


@frappe.whitelist()
def get_locked_prices(team: str | None = None) -> dict:
	"""Where each running subscription's locked rate sits against today's list price.

	A rate is locked when the segment opens and never re-read (ADR 0010), so a catalog
	increase leaves the customer where they were. That protection is invisible unless
	we show it.
	"""
	team = _resolve_team(team)
	currency = _team_currency(team)

	rows = []
	monthly_saving = 0.0
	for segment in team_active_segments(team):
		listed = list_rate_for(segment, currency)
		locked = frappe.utils.flt(segment.locked_rate)
		gap = frappe.utils.flt(listed - locked, 2) if listed is not None else 0.0
		if gap > 0:
			monthly_saving += gap
		rows.append(
			{
				"subscription": segment.subscription,
				"title": _title_for(segment.resource_id, segment),
				"plan": segment.plan,
				"cluster": segment.cluster,
				"locked_rate": locked,
				# None where the plan has no rate in this currency/region today — an
				# unpriced plan is not a saving of the whole rate.
				"list_rate": listed,
				"saving": max(gap, 0.0),
				# The lock cuts both ways: where the catalog has since fallen below what
				# this segment locked, the customer is paying over today's list. Never
				# report that as a negative saving — say it, so re-locking is a choice
				# they can make rather than something we quietly sat on.
				"above_list": gap < 0,
				"above_list_by": frappe.utils.flt(-gap, 2) if gap < 0 else 0.0,
				"locked_at": _locked_at(segment.subscription),
			}
		)

	rows.sort(key=lambda r: r["saving"], reverse=True)
	return {
		"currency": currency,
		"rows": rows,
		"monthly_saving": frappe.utils.flt(monthly_saving, 2),
		"annual_saving": frappe.utils.flt(monthly_saving * 12, 2),
		"protected_count": sum(1 for r in rows if r["saving"] > 0),
		"above_list_count": sum(1 for r in rows if r["above_list"]),
	}


def _projected_lines(team: str, today) -> list:
	"""This cycle's lines from the billing engine — the same ones the forecast quotes."""
	from central.billing.projection import engine

	projection = engine.project(
		team,
		frappe.utils.get_first_day(today),
		frappe.utils.get_last_day(today),
		today=today,
		guarded=False,
	)
	return (projection["invoice"] or {}).get("lines") or []


def _cost_by_resource(lines) -> dict:
	"""Sum line amounts per resource. A resize mid-cycle splits one resource across
	several lines, and a metered subject adds an overage line to its own bundle."""
	totals: dict = {}
	for line in lines:
		line = frappe._dict(line)
		resource_id = line.subscription_resource
		if not resource_id:
			continue
		totals[resource_id] = frappe.utils.flt(totals.get(resource_id, 0.0) + frappe.utils.flt(line.amount), 2)
	return totals


def _metered_usage(team: str) -> dict:
	"""Usage against the locked allowance, per metered subject, for this period."""
	usage: dict = {}
	rows = frappe.get_all(
		"Usage Rollup",
		filters={
			"team": team,
			"period_start": [">=", frappe.utils.get_first_day(frappe.utils.getdate())],
			"superseded_by": ["is", "not set"],
		},
		fields=["resource_id", "quantity", "unit", "locked_allowance"],
	)
	for row in rows:
		allowance = frappe.utils.flt(row.locked_allowance)
		if not allowance:
			continue
		current = usage.setdefault(
			row.resource_id, {"used": 0.0, "allowance": allowance, "unit": row.unit}
		)
		current["used"] = frappe.utils.flt(current["used"] + frappe.utils.flt(row.quantity), 2)
	for entry in usage.values():
		entry["over"] = entry["used"] > entry["allowance"]
	return usage


def _title_for(resource_id: str, segment) -> str:
	"""What to call the thing on screen: the Asset's own name for a server, the plan
	title for a team-level service, and the raw subject only as a last resort."""
	if segment and segment.asset_id:
		title = frappe.db.get_value("Asset", segment.asset_id, "title")
		if title:
			return title
	if segment and segment.plan:
		title = frappe.db.get_value("Plan", segment.plan, "title")
		if title:
			return title
	return resource_id


def list_rate_for(segment, currency: str):
	"""What this subscription would cost if it were provisioned today.

	A preset resolves to its plan's catalog rate; a composed config is re-summed from
	the component rate card, because that is how it was priced in the first place
	(ADR 0009).
	"""
	from central.billing.catalog import pricing

	if segment.pricing_mode == "Composed":
		includes = frappe.get_all(
			"Plan Includes",
			filters={"parent": segment.subscription, "parenttype": "Subscription"},
			fields=["resource_type", "quantity"],
		)
		if not includes:
			return None
		return pricing.resolve_config_rate(includes, currency, segment.cluster)

	if not segment.plan:
		return None
	return pricing.resolve_rate(pricing.get_catalog_rates("Plan", segment.plan), currency, segment.cluster)


def _locked_at(subscription: str) -> str | None:
	"""When the open segment's rate was struck."""
	rows = frappe.get_all(
		"Subscription Change",
		filters={"subscription": subscription, "change_type": ["in", ("Created", "Plan Changed")]},
		fields=["effective_at"],
		order_by="effective_at desc, creation desc",
		limit=1,
	)
	return str(rows[0].effective_at) if rows and rows[0].effective_at else None
