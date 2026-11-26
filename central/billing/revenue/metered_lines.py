# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from central.billing.catalog.plan_setup import AI_RESOURCE_TYPE

# The Invoice Line Item description is a Data field.
MAXIMUM_DESCRIPTION = 140


def line_description(rollup, rate: float) -> str:
	"""What an invoice line adds to its resource: the dimension, and the rate it was converted at."""
	conversion = ""
	if rollup.rate_date:
		conversion = _("1 {0} = {1}, rate of {2}").format(
			rollup.unit, frappe.utils.fmt_money(rate, currency=rollup.currency), rollup.rate_date
		)
	# The conversion is kept whole; a long dimension gives way.
	room = MAXIMUM_DESCRIPTION - len(conversion) - (3 if conversion else 0)
	return " · ".join(part for part in ((rollup.dimension or "")[:room], conversion) if part)


def month_rows(team: str, clusters: list, period_start, period_end_excl, team_level: bool) -> list:
	"""The team's counted usage months in the period, shaped as rollups."""
	table = frappe.qb.DocType("Usage Month")
	in_scope = rollups_in(table, clusters, team_level)
	if in_scope is None:
		return []
	return (
		frappe.qb.from_(table)
		.select(
			table.resource_id,
			table.resource_type,
			table.dimension,
			table.quantity,
			table.unit,
			table.currency,
			table.locked_allowance,
			table.locked_rate,
			table.rate_date,
			table.cluster,
		)
		.where(table.team == team)
		.where(in_scope)
		# Only the row a recount rated bills; the other rows of the month only hold days.
		.where(table.counted_at.isnotnull())
		.where(table.month >= frappe.utils.getdate(period_start))
		.where(table.month < period_end_excl)
	).run(as_dict=True)


def rollups_in(table, clusters: list, team_level: bool):
	"""Rollups in one of `clusters`, and with `team_level` the team's AI usage, which has no cluster."""
	condition = _in_clusters(table.cluster, clusters) if clusters else None
	if not team_level:
		return condition
	# Only AI: another service's blank-cluster rollups were never billed by the team run.
	ai = _is_blank(table.cluster) & (table.resource_type == AI_RESOURCE_TYPE)
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
