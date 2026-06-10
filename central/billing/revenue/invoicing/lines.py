# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The day-weighted line-item engine — fixed charges from the price-lock
run-segments. Shared by draft generation and the dashboard forecast.
"""

import frappe


def _days_in_period(period_start, period_end) -> int:
	return (frappe.utils.getdate(period_end) - frappe.utils.getdate(period_start)).days + 1


def compute_line_items(team: str, cluster: str, period_start, period_end) -> list[dict]:
	"""Day-weighted line items for a (team, cluster) over the billing month.

	One line per price-lock run-segment overlapping the period. `ended_at` is
	exclusive — the day of a plan change belongs to the new plan ("new plan wins
	the day"). A segment that opened and closed within a single day still bills
	one day (the max(1,...) floor closes the same-day-churn free faucet). The
	zero-length `cancelled` terminal markers are skipped.
	"""
	period_start = frappe.utils.getdate(period_start)
	period_end = frappe.utils.getdate(period_end)
	period_end_excl = frappe.utils.add_days(period_end, 1)
	units = _days_in_period(period_start, period_end)

	segments = frappe.get_all(
		"Price Lock",
		filters={
			"team": team,
			"cluster": cluster,
			"event_type": ["!=", "cancelled"],
		},
		fields=["name", "resource_id", "plan", "locked_rate", "started_at", "ended_at"],
		order_by="started_at asc",
	)

	lines = []
	for seg in segments:
		seg_start = frappe.utils.getdate(seg.started_at)
		seg_end_excl = frappe.utils.getdate(seg.ended_at) if seg.ended_at else period_end_excl

		# Clamp to the billing period.
		start = max(seg_start, period_start)
		end_excl = min(seg_end_excl, period_end_excl)
		if start >= period_end_excl or end_excl <= period_start:
			continue  # no overlap with this month

		days = max(1, (end_excl - start).days)
		rate = frappe.utils.flt(seg.locked_rate)
		amount = frappe.utils.flt(days * rate / units, 2)
		lines.append(
			{
				"subscription_resource": seg.resource_id,
				"plan": seg.plan,
				"cluster": cluster,
				"resource_type": "bundle",
				"unit": "day",
				"quantity": 1,
				"rate": rate,
				"days": days,
				"amount": amount,
			}
		)
	return lines
