# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Metered usage for a period that has not happened yet.

Fixed charges project into a future month for free: the rate is locked on the
subscription's change row and the days are arithmetic, so the existing line engine
answers a September question in August without being told anything new.

Metering cannot. `metered_line_items_for_clusters` selects `Usage Rollup` rows *within
the period*, and a future month has none — so left alone it returns an empty list and
the projection quietly loses every metered charge. That failure is worse than a
missing feature: it understates the bill, which is the direction that reassures, and a
fixed-only invoice looks exactly like a complete one on screen.

So usage is inferred, and the inference is labelled. Nothing here re-implements
pricing — allowance, live-vs-grandfathered rates, prepaid-pack exclusion and the
unpriced-overage guard all live in `metering`, and this drives that same code over a
window that *did* happen, then scales the result.
"""

import frappe

from central.billing.projection.basis import ESTIMATED, MEASURED, mark
from central.billing.revenue.metering import metered_line_items_for_clusters

TRAILING_MONTHS = 3

# Identity of a metered line across periods — what we merge trailing history on.
_KEY = ("subscription_resource", "resource_type", "cluster", "unit")


def metered_lines(team: str, clusters, period_start, period_end, today=None) -> list[dict]:
	"""The period's metered lines, measured where usage has landed and estimated where
	it has not.

	Three cases, and which one applies is decided by the calendar rather than by a flag:
	a closed period is entirely fact; a period in flight is scaled from what has landed
	so far; a period that has not started is inferred from the trailing window.
	"""
	today = frappe.utils.getdate(today or frappe.utils.nowdate())
	start = frappe.utils.getdate(period_start)
	end = frappe.utils.getdate(period_end)

	if end < today:
		return mark(
			metered_line_items_for_clusters(team, clusters, start, end, explain=True), MEASURED
		)

	if start <= today:
		landed = metered_line_items_for_clusters(team, clusters, start, end, explain=True)
		elapsed = (today - start).days + 1
		total = (end - start).days + 1
		return _scaled(landed, elapsed, total)

	return _from_trailing(team, clusters, start)


def _scaled(lines: list[dict], elapsed: int, total: int) -> list[dict]:
	"""Project a part-month's usage across the whole month.

	The result is an estimate even when the arithmetic is exact, because the days it
	covers have not happened — a customer who doubles their traffic tomorrow makes this
	wrong, and the label is what says so.
	"""
	if not lines or elapsed <= 0:
		return []
	factor = total / elapsed
	out = []
	for line in lines:
		projected = dict(line)
		projected["quantity"] = frappe.utils.flt(line.get("quantity") * factor, 4)
		projected["amount"] = frappe.utils.flt(line.get("amount") * factor, 2)
		projected["basis"] = ESTIMATED
		projected["estimated_from"] = f"run rate over {elapsed} of {total} days"
		projected["derivation"] = {
			"mode": "Estimated",
			"why": "the month is part elapsed, so what has landed is projected across it",
			"observed_amount": frappe.utils.flt(line.get("amount"), 2),
			"elapsed_days": elapsed,
			"period_days": total,
			"arithmetic": f"{frappe.utils.flt(line.get('amount'), 2)} × {total} ÷ {elapsed}",
			"measured_basis": line.get("derivation"),
		}
		out.append(projected)
	return out


def _window(period_start, months: int = TRAILING_MONTHS):
	"""The whole months immediately before the period being projected."""
	end = frappe.utils.add_days(frappe.utils.get_first_day(period_start), -1)
	start = frappe.utils.get_first_day(frappe.utils.add_months(end, -(months - 1)))
	return start, end


def _from_trailing(team: str, clusters, period_start, months: int = TRAILING_MONTHS) -> list[dict]:
	"""Average the trailing window's real, priced metered lines into one projected month.

	Averaging *amounts* rather than quantities is deliberate: the allowance is monthly, so
	each historical month has already had its own allowance applied by the real pricing
	path. Averaging raw quantity and deducting a single allowance would forgive usage the
	customer was actually billed for.
	"""
	start, end = _window(period_start, months)
	history = metered_line_items_for_clusters(team, clusters, start, end, explain=True)
	if not history:
		# No history is not zero usage — it is silence. Projecting a zero line would
		# assert something we do not know, so nothing is projected for this resource.
		return []

	merged: dict = {}
	observed: dict = {}
	for line in history:
		key = tuple(line.get(f) for f in _KEY)
		agg = merged.setdefault(key, {**line, "quantity": 0.0, "amount": 0.0})
		agg["quantity"] += frappe.utils.flt(line.get("quantity"))
		agg["amount"] += frappe.utils.flt(line.get("amount"))
		observed[key] = observed.get(key, 0.0) + frappe.utils.flt(line.get("amount"))

	out = []
	for key, line in merged.items():
		line["quantity"] = frappe.utils.flt(line["quantity"] / months, 4)
		line["amount"] = frappe.utils.flt(line["amount"] / months, 2)
		line["basis"] = ESTIMATED
		line["estimated_from"] = f"{months}-month average to {end}"
		line["derivation"] = {
			"mode": "Estimated",
			"why": "the period has not started, so usage is inferred from what did happen",
			"window_from": str(start),
			"window_to": str(end),
			"months": months,
			"observed_total": frappe.utils.flt(observed[key], 2),
			"arithmetic": f"{frappe.utils.flt(observed[key], 2)} ÷ {months}",
		}
		out.append(line)
	return out
