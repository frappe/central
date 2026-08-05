# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The time-weighted line-item engine — fixed charges from Subscription Change
rate-snapshot segments. Shared by draft generation and the dashboard forecast.

Billing is daily by default: a stable config (one held for 24h or more) bills a
whole day at a time, so a normal month reads as a handful of clean day lines and
a full day always costs one day's rate — the "daily cap".

Hourly billing kicks in only when a machine *churns*: two config changes less
than 24h apart (a resize twice in a day, or a peak-then-drop even across
midnight). Any calendar date a churn segment touches is billed by the exact hours
each config ran that date, which closes the sub-day gaming loophole and bills a
short-lived config fairly. Because a date is billed either daily OR hourly — never
both — the two passes partition the period and the total stays exact.
"""

from datetime import datetime, time, timedelta

import frappe

from central.billing.catalog.subscriptions import _asset_clusters

CHURN_WINDOW_HOURS = 24


def _days_in_period(period_start, period_end) -> int:
	return (frappe.utils.getdate(period_end) - frappe.utils.getdate(period_start)).days + 1


def _dates_touched(start_dt: datetime, end_dt: datetime) -> list:
	"""Calendar dates the half-open [start, end) datetime interval overlaps."""
	out = []
	d = start_dt.date()
	while datetime.combine(d, time.min) < end_dt:
		out.append(d)
		d += timedelta(days=1)
	return out


def compute_line_items(team: str, cluster: str, period_start, period_end) -> list[dict]:
	"""Time-weighted fixed line items for one (team, cluster) over the billing month.

	Each `Created`/`Plan Changed` Subscription-Change row opens a segment at its
	`locked_rate` snapshot that runs until the subscription's next change (or the
	period end). `Cancelled` rows close the prior segment and carry no rate. A
	segment held < 24h marks every date it touches as a churn date; those dates
	bill hourly, all others bill daily.

	Single-cluster entry point — the dashboard forecast asks per cluster. The monthly
	run bills a whole team at once and uses `team_line_items` instead, which reads the
	team's subscriptions once rather than once per cluster.
	"""
	subscriptions = frappe.get_all("Subscription", filters={"team": team}, fields=["name", "asset_id"])
	# Resolve every asset's cluster in one query (not a get_value per subscription),
	# then keep only the subs whose asset runs in this cluster.
	clusters = _asset_clusters([s.asset_id for s in subscriptions])
	subscriptions = [s for s in subscriptions if clusters.get(s.asset_id) == cluster]
	if not subscriptions:
		return []

	# All these subscriptions' changes in one query, grouped by subscription — not a
	# query per subscription.
	changes_by_sub = _changes_by_subscription([s.name for s in subscriptions])

	bounds = _period_bounds(period_start, period_end)
	lines = []
	for sub in subscriptions:
		lines += _subscription_lines(sub, cluster, changes_by_sub.get(sub.name, []), bounds)
	return lines


def team_line_items(team: str, period_start, period_end) -> list[dict]:
	"""Every fixed line item for a team across all the clusters it runs in, from ONE
	read of its subscriptions, their asset clusters and their changes.

	The monthly run bills a team as one consolidated invoice, so it wants all the
	team's lines together. Looping clusters and calling `compute_line_items` per cluster
	re-reads the whole team once per cluster; this reads it once and tags each line with
	its own subscription's cluster. The union of lines is identical either way.
	"""
	subscriptions = frappe.get_all("Subscription", filters={"team": team}, fields=["name", "asset_id"])
	clusters = _asset_clusters([s.asset_id for s in subscriptions])
	changes_by_sub = _changes_by_subscription([s.name for s in subscriptions])

	bounds = _period_bounds(period_start, period_end)
	lines = []
	for sub in subscriptions:
		cluster = clusters.get(sub.asset_id)
		if not cluster:
			continue  # no live asset cluster — nothing to bill this subscription against
		lines += _subscription_lines(sub, cluster, changes_by_sub.get(sub.name, []), bounds)
	return lines


def _period_bounds(period_start, period_end):
	"""The period's date range and its daily/hourly denominators, computed once and
	shared across every subscription instead of recomputed per (team, cluster) call."""
	ps = frappe.utils.getdate(period_start)
	pe = frappe.utils.getdate(period_end)
	day_units = _days_in_period(ps, pe)  # daily denominator
	return frappe._dict(
		ps=ps,
		pe=pe,
		period_start_dt=datetime.combine(ps, time.min),
		period_end_excl_dt=datetime.combine(pe + timedelta(days=1), time.min),
		day_units=day_units,
		hour_units=day_units * 24,  # hourly denominator
	)


def _subscription_lines(sub, cluster: str, changes: list, b) -> list[dict]:
	"""The daily/hourly fixed lines for one subscription in one cluster.

	Splits the subscription's rate-snapshot changes into billable segments, marks the
	churn dates (a segment held < 24h), then bills each date either daily or hourly —
	never both — so the two passes partition the period and the total stays exact.
	"""
	# Build the billable segments (clamped to the period), flagging churn from the
	# real held duration (unclamped) so a resize near the period edge still counts.
	segs = []
	for i, change in enumerate(changes):
		if change.change_type == "Cancelled" or change.locked_rate is None:
			continue  # terminal marker or no rate snapshot — not a billable segment
		seg_start_dt = frappe.utils.get_datetime(change.effective_at)
		seg_end_dt = (
			frappe.utils.get_datetime(changes[i + 1].effective_at)
			if i + 1 < len(changes)
			else b.period_end_excl_dt
		)
		held_hours = (seg_end_dt - seg_start_dt).total_seconds() / 3600.0
		start = max(seg_start_dt, b.period_start_dt)
		end = min(seg_end_dt, b.period_end_excl_dt)
		if start >= b.period_end_excl_dt or end <= b.period_start_dt:
			continue  # no overlap with this month
		segs.append(
			{
				"start": start,
				"end": end,
				"rate": frappe.utils.flt(change.locked_rate),
				"plan": change.new_value,
				"asset": sub.asset_id,
				"cluster": cluster,
				"churn": held_hours < CHURN_WINDOW_HOURS,
			}
		)

	# A churn segment (< 24h) turns every date it touches into an hourly date; the
	# 24h window spans midnight, so a cross-day churn marks both dates.
	churn_dates = set()
	for s in segs:
		if s["churn"]:
			churn_dates.update(_dates_touched(s["start"], s["end"]))

	lines = []
	for s in segs:
		# Daily pass — whole non-churn dates the segment owns. A date belongs to
		# the config active at its start (the change-date boundary), so a single
		# mid-day resize still sends the whole transition day to one plan.
		d0 = max(s["start"].date(), b.ps)
		d1 = min(s["end"].date(), b.pe + timedelta(days=1))  # exclusive
		days = 0
		d = d0
		while d < d1:
			if d not in churn_dates:
				days += 1
			d += timedelta(days=1)
		if days:
			lines.append(_daily_line(s, days, b.day_units))

		# Hourly pass — this segment's real hours on each churn date it touches.
		for cd in _dates_touched(s["start"], s["end"]):
			if cd not in churn_dates:
				continue
			day_start = max(s["start"], datetime.combine(cd, time.min))
			day_end = min(s["end"], datetime.combine(cd + timedelta(days=1), time.min))
			hours = (day_end - day_start).total_seconds() / 3600.0
			if hours > 0:
				lines.append(_hourly_line(s, hours, b.hour_units, cd))
	return lines


def _changes_by_subscription(subscription_names: list[str]) -> dict:
	"""Every billable-segment change for these subscriptions in one query, grouped by
	subscription and kept in (effective_at, creation) order — the order the segment
	builder in `compute_line_items` depends on."""
	if not subscription_names:
		return {}
	rows = frappe.get_all(
		"Subscription Change",
		filters={
			"subscription": ["in", subscription_names],
			"change_type": ["in", ["Created", "Plan Changed", "Cancelled"]],
		},
		fields=["subscription", "change_type", "new_value", "locked_rate", "effective_at"],
		# Secondary sort on creation so changes sharing an effective_at (e.g. a
		# same-instant provision then cancel) order deterministically by when they were
		# recorded — otherwise a Cancelled could sort ahead of its Created.
		order_by="effective_at asc, creation asc",
	)
	grouped: dict = {}
	for r in rows:
		grouped.setdefault(r.subscription, []).append(r)
	return grouped


def _daily_line(seg: dict, days: int, day_units: int) -> dict:
	return {
		"subscription_resource": seg["asset"],
		"plan": seg["plan"],
		"cluster": seg["cluster"],
		"resource_type": "bundle",
		"unit": "day",
		"quantity": 1,
		"rate": seg["rate"],
		"days": days,
		"hours": None,
		"amount": frappe.utils.flt(days * seg["rate"] / day_units, 2),
	}


def _hourly_line(seg: dict, hours: float, hour_units: int, charge_date) -> dict:
	return {
		"subscription_resource": seg["asset"],
		"plan": seg["plan"],
		"cluster": seg["cluster"],
		"resource_type": "bundle",
		"unit": "hour",
		"quantity": 1,
		"rate": seg["rate"],
		"days": None,
		"hours": frappe.utils.flt(hours, 2),
		"charge_date": charge_date,
		"amount": frappe.utils.flt(hours * seg["rate"] / hour_units, 2),
	}
