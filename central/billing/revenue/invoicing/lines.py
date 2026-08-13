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


def compute_line_items(
	team: str, cluster: str, period_start, period_end, explain: bool = False, changes=None
) -> list[dict]:
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
	changes_by_sub = _resolve_changes([s.name for s in subscriptions], changes)

	bounds = _period_bounds(period_start, period_end)
	lines = []
	for sub in subscriptions:
		lines += _subscription_lines(sub, cluster, changes_by_sub.get(sub.name, []), bounds, explain)
	return lines


def team_line_items(team: str, period_start, period_end, explain: bool = False, changes=None) -> list[dict]:
	"""Every fixed line item for a team across all the clusters it runs in, from ONE
	read of its subscriptions, their asset clusters and their changes.

	The monthly run bills a team as one consolidated invoice, so it wants all the
	team's lines together. Looping clusters and calling `compute_line_items` per cluster
	re-reads the whole team once per cluster; this reads it once and tags each line with
	its own subscription's cluster. The union of lines is identical either way.
	"""
	subscriptions = frappe.get_all("Subscription", filters={"team": team}, fields=["name", "asset_id"])
	clusters = _asset_clusters([s.asset_id for s in subscriptions])
	changes_by_sub = _resolve_changes([s.name for s in subscriptions], changes)

	bounds = _period_bounds(period_start, period_end)
	lines = []
	for sub in subscriptions:
		cluster = clusters.get(sub.asset_id)
		if not cluster:
			continue  # no live asset cluster — nothing to bill this subscription against
		lines += _subscription_lines(sub, cluster, changes_by_sub.get(sub.name, []), bounds, explain)
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


def _subscription_lines(sub, cluster: str, changes: list, b, explain: bool = False) -> list[dict]:
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
				# When the rate was actually locked, before any clamping to this billing
				# window. `start` answers "what does this month bill"; this answers "when
				# was this price set", which is what grandfathering turns on — and the two
				# are the same only in the month a resource was provisioned.
				"opened_at": seg_start_dt,
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
		billed_dates = []
		d = d0
		while d < d1:
			if d not in churn_dates:
				billed_dates.append(d)
			d += timedelta(days=1)
		if billed_dates:
			lines.append(_daily_line(s, len(billed_dates), b.day_units, explain, billed_dates))

		# Hourly pass — this segment's real hours on each churn date it touches.
		for cd in _dates_touched(s["start"], s["end"]):
			if cd not in churn_dates:
				continue
			day_start = max(s["start"], datetime.combine(cd, time.min))
			day_end = min(s["end"], datetime.combine(cd + timedelta(days=1), time.min))
			hours = (day_end - day_start).total_seconds() / 3600.0
			if hours > 0:
				# Which configs shared this date is the whole explanation for why it went
				# hourly, so carry them rather than leaving the reader to infer it.
				touching = [
					{
						"from": str(other["start"]),
						"to": str(other["end"]),
						"rate": other["rate"],
						"plan": other["plan"],
						"held_under_24h": other["churn"],
					}
					for other in segs
					if cd in _dates_touched(other["start"], other["end"])
				]
				lines.append(
					_hourly_line(
						s, hours, b.hour_units, cd, explain, touching, window=(day_start, day_end)
					)
				)

	# Chronological. The loop above walks segment by segment, emitting each one's
	# whole-day line before its hourly slivers, so the rows came out grouped by
	# segment rather than in the order the changes happened — a resize read as a
	# jumble instead of a sequence.
	lines.sort(key=lambda ln: (ln.get("period_from") or datetime.max, ln.get("unit") == "hour"))
	return lines


def _resolve_changes(subscription_names: list[str], changes=None) -> dict:
	"""Where the rate-snapshot segments come from.

	The run reads them from Subscription Change, which is the only source there is. A
	projection may supply its own — the real rows plus a hypothetical resize, say — so
	that an invented change is rated by exactly the code that rates a real one, churn
	window and all. `changes` is either a ready-made mapping or a callable taking the
	subscription names; absent, nothing changes.
	"""
	if changes is None:
		return _changes_by_subscription(subscription_names)
	if callable(changes):
		return changes(subscription_names)
	return changes


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


def _daily_line(seg: dict, days: int, day_units: int, explain: bool = False, billed_dates=None) -> dict:
	line = {
		"subscription_resource": seg["asset"],
		"plan": seg["plan"],
		"cluster": seg["cluster"],
		"resource_type": "bundle",
		"unit": "day",
		"quantity": 1,
		"rate": seg["rate"],
		"days": days,
		"hours": None,
		# The window this line actually billed. Without it a resized month is a list
		# of durations with no order and no "when" — six lines saying "13 day(s)"
		# and "16 hour(s)" that the reader has to reassemble into a sequence.
		"period_from": datetime.combine(min(billed_dates), time.min) if billed_dates else None,
		"period_to": datetime.combine(max(billed_dates) + timedelta(days=1), time.min)
		if billed_dates
		else None,
		"amount": frappe.utils.flt(days * seg["rate"] / day_units, 2),
	}
	if explain:
		line["derivation"] = {
			"mode": "Daily",
			"why": "the config was held for a day or more, so whole days are billed",
			"segment_from": str(seg["start"]),
			"segment_to": str(seg["end"]),
			"rate_locked_at": str(seg["opened_at"]),
			"locked_rate": seg["rate"],
			"days": days,
			"day_units": day_units,
			"dates": [str(d) for d in (billed_dates or [])],
			"arithmetic": f"{days} ÷ {day_units} × {seg['rate']}",
		}
	return line


def _hourly_line(
	seg: dict,
	hours: float,
	hour_units: int,
	charge_date,
	explain: bool = False,
	touching=None,
	window=None,
) -> dict:
	line = {
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
		"period_from": window[0] if window else None,
		"period_to": window[1] if window else None,
		"amount": frappe.utils.flt(hours * seg["rate"] / hour_units, 2),
	}
	if explain:
		line["derivation"] = {
			"mode": "Hourly",
			"why": (
				"a config on this date was held for less than 24 hours, so the whole date bills by the hour"
			),
			"charge_date": str(charge_date),
			"segment_from": str(seg["start"]),
			"segment_to": str(seg["end"]),
			"rate_locked_at": str(seg["opened_at"]),
			"locked_rate": seg["rate"],
			"hours": frappe.utils.flt(hours, 2),
			"hour_units": hour_units,
			"dates": [str(charge_date)],
			"configs_on_this_date": touching or [],
			"arithmetic": f"{frappe.utils.flt(hours, 2)} ÷ {hour_units} × {seg['rate']}",
		}
	return line
