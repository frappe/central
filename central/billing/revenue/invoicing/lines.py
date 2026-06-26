# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The day-weighted line-item engine — fixed charges from Subscription Change
rate-snapshot segments. Shared by draft generation and the dashboard forecast.
"""

import frappe


def _days_in_period(period_start, period_end) -> int:
	return (frappe.utils.getdate(period_end) - frappe.utils.getdate(period_start)).days + 1


def compute_line_items(team: str, cluster: str, period_start, period_end) -> list[dict]:
	"""Day-weighted line items for a (team, cluster) over the billing month.

	One line per Subscription-Change run-segment overlapping the period: each
	`Created`/`Plan Changed` row opens a segment at its `locked_rate` snapshot
	that runs until the subscription's next change (or the period end, if still
	open). `Cancelled` rows close the prior segment and carry no rate of their
	own. A segment that opened and closed within a single day still bills one
	day (the max(1,...) floor closes the same-day-churn free faucet).
	"""
	period_start = frappe.utils.getdate(period_start)
	period_end = frappe.utils.getdate(period_end)
	period_end_excl = frappe.utils.add_days(period_end, 1)
	units = _days_in_period(period_start, period_end)

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
		for i, change in enumerate(changes):
			if change.change_type == "Cancelled" or change.locked_rate is None:
				continue  # terminal marker or no rate snapshot — not a billable segment

			seg_start = frappe.utils.getdate(change.effective_at)
			seg_end_excl = (
				frappe.utils.getdate(changes[i + 1].effective_at)
				if i + 1 < len(changes)
				else period_end_excl
			)

			# Clamp to the billing period.
			start = max(seg_start, period_start)
			end_excl = min(seg_end_excl, period_end_excl)
			if start >= period_end_excl or end_excl <= period_start:
				continue  # no overlap with this month

			days = max(1, (end_excl - start).days)
			rate = frappe.utils.flt(change.locked_rate)
			amount = frappe.utils.flt(days * rate / units, 2)
			lines.append(
				{
					"subscription_resource": sub.asset_id,
					"plan": change.new_value,
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
