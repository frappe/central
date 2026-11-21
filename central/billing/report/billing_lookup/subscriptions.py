# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.catalog.subscriptions import active_segments, uncancelled_subscriptions
from central.billing.doctype.subscription_change.subscription_change import (
	CLOSING_CHANGE_TYPES,
	OPENING_CHANGE_TYPES,
)
from central.billing.report.billing_lookup.layout import column

CHANGE_LIMIT = 50


def running(team: str) -> tuple[list, list]:
	"""Every subscription not cancelled, with what it costs a month now, and a total per currency."""
	names = uncancelled_subscriptions({"team": team})
	subs = frappe.get_all(
		"Subscription",
		filters={"name": ["in", names or [""]]},
		fields=["name", "plan", "server_id", "cluster", "account_standing", "billing_cycle"],
		order_by="creation asc",
	)
	segments = {s.subscription: s for s in active_segments({"team": team})}
	regions = dict(frappe.get_all("Region", fields=["name", "display_name"], as_list=True))
	rows = [_running_row(sub, segments.get(sub.name), regions) for sub in subs]
	return [
		column(_("Subscription"), "subscription", "Link", 150, options="Subscription"),
		column(_("Plan"), "plan", "Link", 200, options="Plan"),
		column(_("Server"), "server_id", "Data", 150),
		column(_("Region"), "region", "Data", 110),
		column(_("Billing"), "state", "Data", 100),
		column(_("Standing"), "account_standing", "Data", 110),
		column(_("Monthly Cost"), "monthly_cost", "Currency", 140, options="currency"),
	], rows + _total_rows(rows)


def monthly_cost_cards(team: str) -> list[dict]:
	"""What the team's running subscriptions cost a month, one card per currency."""
	totals = _totals(_monthly_segments(team))
	if not totals:
		return [{"label": _("Monthly Cost"), "value": _("Nothing running"), "datatype": "Data"}]
	return [
		{
			"label": _("Monthly Cost ({0})").format(currency),
			"value": amount,
			"datatype": "Currency",
			"currency": currency,
			"indicator": "blue",
		}
		for currency, amount in totals.items()
	]


def changes(team: str) -> tuple[list, list]:
	"""The latest subscription changes, each with the monthly cost after it and the difference."""
	cycles = dict(
		frappe.get_all("Subscription", filters={"team": team}, fields=["name", "billing_cycle"], as_list=True)
	)
	rows = frappe.get_all(
		"Subscription Change",
		filters={"team": team},
		fields=[
			"effective_at",
			"subscription",
			"change_type",
			"old_value",
			"new_value",
			"locked_rate",
			"currency",
		],
		order_by="effective_at asc, creation asc",
	)
	cost_now: dict[str, float] = {}
	for row in rows:
		_price_change(row, cost_now, cycles.get(row.subscription))
	return [
		column(_("When"), "effective_at", "Datetime", 170),
		column(_("Subscription"), "subscription", "Link", 150, options="Subscription"),
		column(_("Change"), "change_type", "Data", 140),
		column(_("From"), "old_value", "Data", 180),
		column(_("To"), "new_value", "Data", 180),
		column(_("Monthly Cost After"), "cost_after", "Currency", 150, options="currency"),
		column(_("Change in Cost"), "cost_change", "Currency", 140, options="currency"),
		column(_("Effect"), "effect", "Data", 120),
	], list(reversed(rows))[:CHANGE_LIMIT]


def _running_row(sub, segment, regions: dict) -> dict:
	region = (segment and segment.cluster) or sub.cluster
	return {
		"subscription": sub.name,
		"plan": sub.plan,
		"server_id": sub.server_id,
		"region": regions.get(region) or region,
		"state": _("Running") if segment else _("Paused"),
		"account_standing": sub.account_standing,
		"monthly_cost": _monthly(segment.locked_rate, sub.billing_cycle) if segment else None,
		"currency": segment.currency if segment else None,
	}


def _total_rows(rows: list[dict]) -> list[dict]:
	return [
		{"plan": _("Total"), "monthly_cost": amount, "currency": currency, "is_total": 1}
		for currency, amount in _totals(
			(r["currency"], r["monthly_cost"]) for r in rows if r["currency"]
		).items()
	]


def _monthly_segments(team: str):
	cycles = dict(
		frappe.get_all("Subscription", filters={"team": team}, fields=["name", "billing_cycle"], as_list=True)
	)
	for segment in active_segments({"team": team}):
		yield segment.currency, _monthly(segment.locked_rate, cycles.get(segment.subscription))


def _totals(pairs) -> dict[str, float]:
	totals: dict[str, float] = {}
	for currency, amount in pairs:
		totals[currency] = flt(totals.get(currency, 0.0) + amount, 2)
	return dict(sorted(totals.items()))


def _monthly(rate: float, billing_cycle: str | None) -> float:
	return flt(rate) / 12 if billing_cycle == "Annual" else flt(rate)


def _price_change(row, cost_now: dict[str, float], billing_cycle: str | None) -> None:
	"""Set the cost after the change, the difference and its effect; a change that does not
	touch the price (a standing or method change) gets none."""
	before = cost_now.get(row.subscription, 0.0)
	if row.change_type in CLOSING_CHANGE_TYPES:
		after = 0.0
	elif row.change_type in OPENING_CHANGE_TYPES or row.change_type == "Plan Changed":
		after = _monthly(row.locked_rate, billing_cycle)
	else:
		return
	cost_now[row.subscription] = after
	row.cost_after, row.cost_change = after, flt(after - before, 2)
	row.effect = _effect(row.change_type, row.cost_change)


def _effect(change_type: str, difference: float) -> str:
	if change_type in CLOSING_CHANGE_TYPES:
		return _("Billing stopped")
	if change_type in OPENING_CHANGE_TYPES:
		return _("Billing started")
	if difference > 0:
		return _("Upgrade")
	return _("Downgrade") if difference < 0 else _("Same price")
