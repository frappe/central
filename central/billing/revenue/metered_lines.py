# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.catalog.plan_setup import AI_RESOURCE_TYPE
from central.billing.revenue.exchange_rates import month_rate


def billable_quantity(quantity: float, allowance: float) -> float:
	"""The quantity a metered month bills: past the allowance, or a credit when it fell below zero."""
	# Only a meter with no allowance goes below zero: a correction larger than the month's usage.
	if quantity < 0 and not allowance:
		return quantity
	return max(0.0, quantity - allowance)


def line_description(rollup, rate: float) -> str:
	"""What an invoice line adds to its resource: the dimension, and the conversion when it has one."""
	parts = [rollup.dimension] if rollup.dimension else []
	if _is_converted(rollup):
		rate_date = month_rate(rollup.unit, rollup.currency, rollup.period_start).rate_date
		parts.append(
			_("1 {0} = {1}, rate of {2}").format(
				rollup.unit, frappe.utils.fmt_money(rate, currency=rollup.currency), rate_date
			)
		)
	return " · ".join(parts)


def _is_converted(rollup) -> bool:
	"""A rollup counted in money of another currency than the invoice's."""
	return bool(
		rollup.unit
		and rollup.period_start
		and rollup.unit != rollup.currency
		and frappe.db.exists("Currency", rollup.unit)
	)


def rollups_in(rollup, clusters: list, team_level: bool):
	"""Rollups in one of `clusters`, and with `team_level` the team's AI usage, which has no cluster."""
	condition = _in_clusters(rollup.cluster, clusters) if clusters else None
	if not team_level:
		return condition
	# Only AI: another service's blank-cluster rollups were never billed by the team run.
	ai = _is_blank(rollup.cluster) & (rollup.resource_type == AI_RESOURCE_TYPE)
	return ai if condition is None else condition | ai


def _in_clusters(column, clusters: list):
	"""`column` is one of `clusters`. A blank cluster is stored as NULL or "", so it matches both."""
	named = [c for c in clusters if c]
	condition = column.isin(named) if named else None
	if len(named) < len(clusters):
		condition = _is_blank(column) if condition is None else condition | _is_blank(column)
	return condition


def _is_blank(column):
	return column.isnull() | (column == "")
