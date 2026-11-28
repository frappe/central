# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""How a month's days add up to the quantity it bills."""

import calendar

import frappe

from central.billing.revenue.usage_month import PEAKS


def day_weight(day) -> float:
	"""A Level or State day counts as its peak over the days in its own month; a Sum day as its total."""
	quantity = frappe.utils.flt(day.quantity)
	if day.aggregation not in PEAKS:
		return quantity
	return quantity / _days_in_month(day.day)


def billable_above_bundle(days: list, quantity: float) -> float:
	"""The month's quantity above the bundle: each Level or State day above its own, a Sum month above its share."""
	if all(day.aggregation in PEAKS for day in days):
		return sum(
			max(0.0, frappe.utils.flt(day.quantity) - frappe.utils.flt(day.included))
			/ _days_in_month(day.day)
			for day in days
		)
	# A Sum meter writes a day for each day its plan ran, so the bundle scales with those days.
	share = sum(frappe.utils.flt(day.included) / _days_in_month(day.day) for day in days)
	return max(0.0, quantity - share)


def _days_in_month(on) -> int:
	on = frappe.utils.getdate(on)
	return calendar.monthrange(on.year, on.month)[1]
