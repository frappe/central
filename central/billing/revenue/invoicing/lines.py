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
	"""Time-weighted line items for a (team, cluster) over the billing month.

	Each `Created`/`Plan Changed` Subscription-Change row opens a segment at its
	`locked_rate` snapshot that runs until the subscription's next change (or the
	period end). `Cancelled` rows close the prior segment and carry no rate. A
	segment held < 24h marks every date it touches as a churn date; those dates
	bill hourly, all others bill daily.
	"""
	ps = frappe.utils.getdate(period_start)
	pe = frappe.utils.getdate(period_end)
	period_start_dt = datetime.combine(ps, time.min)
	period_end_excl_dt = datetime.combine(pe + timedelta(days=1), time.min)
	day_units = _days_in_period(ps, pe)  # daily denominator
	hour_units = day_units * 24  # hourly denominator

	subscriptions = frappe.get_all(
		"Subscription", filters={"team": team}, fields=["name", "asset_id"]
	)
	subscriptions = [
		s for s in subscriptions
		if s.asset_id and frappe.db.get_value("Asset", s.asset_id, "cluster") == cluster
	]

	lines = []
	for sub in subscriptions:
		changes = frappe.get_all(
			"Subscription Change",
			filters={"subscription": sub.name, "change_type": ["in", ["Created", "Plan Changed", "Cancelled"]]},
			fields=["change_type", "new_value", "locked_rate", "effective_at"],
			# Secondary sort on creation so changes sharing an effective_at (e.g. a
			# same-instant provision then cancel) order deterministically by when they
			# were recorded — otherwise a Cancelled could sort ahead of its Created.
			order_by="effective_at asc, creation asc",
		)

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
				else period_end_excl_dt
			)
			held_hours = (seg_end_dt - seg_start_dt).total_seconds() / 3600.0
			start = max(seg_start_dt, period_start_dt)
			end = min(seg_end_dt, period_end_excl_dt)
			if start >= period_end_excl_dt or end <= period_start_dt:
				continue  # no overlap with this month
			segs.append({
				"start": start, "end": end, "rate": frappe.utils.flt(change.locked_rate),
				"plan": change.new_value, "asset": sub.asset_id, "cluster": cluster,
				"churn": held_hours < CHURN_WINDOW_HOURS,
			})

		# A churn segment (< 24h) turns every date it touches into an hourly date; the
		# 24h window spans midnight, so a cross-day churn marks both dates.
		churn_dates = set()
		for s in segs:
			if s["churn"]:
				churn_dates.update(_dates_touched(s["start"], s["end"]))

		for s in segs:
			# Daily pass — whole non-churn dates the segment owns. A date belongs to
			# the config active at its start (the change-date boundary), so a single
			# mid-day resize still sends the whole transition day to one plan.
			d0 = max(s["start"].date(), ps)
			d1 = min(s["end"].date(), pe + timedelta(days=1))  # exclusive
			days = 0
			d = d0
			while d < d1:
				if d not in churn_dates:
					days += 1
				d += timedelta(days=1)
			if days:
				lines.append(_daily_line(s, days, day_units))

			# Hourly pass — this segment's real hours on each churn date it touches.
			for cd in _dates_touched(s["start"], s["end"]):
				if cd not in churn_dates:
					continue
				day_start = max(s["start"], datetime.combine(cd, time.min))
				day_end = min(s["end"], datetime.combine(cd + timedelta(days=1), time.min))
				hours = (day_end - day_start).total_seconds() / 3600.0
				if hours > 0:
					lines.append(_hourly_line(s, hours, hour_units, cd))
	return lines


def _daily_line(seg: dict, days: int, day_units: int) -> dict:
	return {
		"subscription_resource": seg["asset"], "plan": seg["plan"], "cluster": seg["cluster"],
		"resource_type": "bundle", "unit": "day", "quantity": 1, "rate": seg["rate"],
		"days": days, "hours": None,
		"amount": frappe.utils.flt(days * seg["rate"] / day_units, 2),
	}


def _hourly_line(seg: dict, hours: float, hour_units: int, charge_date) -> dict:
	return {
		"subscription_resource": seg["asset"], "plan": seg["plan"], "cluster": seg["cluster"],
		"resource_type": "bundle", "unit": "hour", "quantity": 1, "rate": seg["rate"],
		"days": None, "hours": frappe.utils.flt(hours, 2), "charge_date": charge_date,
		"amount": frappe.utils.flt(hours * seg["rate"] / hour_units, 2),
	}
