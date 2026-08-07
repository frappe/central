# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""What a cohort of teams is about to be billed, and what happens after.

This report **computes nothing**. A query report executes inside the web request, and
rating a cohort there would be tens of minutes against a two-minute timeout — it does
not degrade, it dies. A background batch does the work and leaves one scalar row per
team; this reads them, like every other report in the module.

Which means the interesting states are the ones where there is nothing to read. A
cohort nobody has projected, and a cohort too large to project, both come back through
the report's `message` slot as a panel with somewhere to go next — not as an error
modal, and not as an empty table with no explanation.
"""

import frappe
from frappe import _

from central.billing.projection import cohort
from central.billing.report._currency import split_currency_columns

# Only the money that has its own column gets split per currency.
MONEY_FIELDS = ("projected_total", "shortfall")


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	batch = filters.batch or _latest_batch(filters)

	if not batch:
		return get_columns(), [], _nothing_projected(filters), None, None

	rows = _rows(batch, filters)
	columns = split_currency_columns(get_columns(), rows, MONEY_FIELDS)
	return columns, rows, _batch_note(batch), None, _summary(rows)


def _latest_batch(filters) -> str | None:
	names = frappe.get_all(
		"Billing Projection Batch",
		filters={"batch_state": ["in", ["Complete", "Partial"]]},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	return names[0] if names else None


def _rows(batch: str, filters) -> list[dict]:
	conditions = {"batch": batch}
	if filters.currency:
		conditions["currency"] = filters.currency
	if filters.outcome:
		conditions["outcome"] = ["like", f"%{filters.outcome}%"]
	if filters.needs_attention:
		conditions["suspends_on"] = ["is", "set"]

	return frappe.get_all(
		"Billing Projection Summary",
		filters=conditions,
		fields=[
			"team", "currency", "projected_total", "measured", "estimated",
			"credit_balance", "shortfall", "settles_via", "outcome", "outcome_reason",
			"due_on", "suspends_on", "as_of",
		],
		order_by="suspends_on asc, projected_total desc",
		limit_page_length=0,
	)


def get_columns() -> list[dict]:
	"""Seven columns, not eleven.

	Five money fields across two currencies is ten columns before Team, and the headings
	truncate. So each column has to earn its place: `Credits` is `Projected total` minus
	`Shortfall`, and the measured/estimated split belongs in the drill-down rather than
	in a list somebody scans. What is left is what an operator acts on — who, how much,
	whether it will settle, and when they get cut off.
	"""
	return [
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 170},
		{"label": _("Projected"), "fieldname": "projected_total", "fieldtype": "Currency",
		 "options": "currency", "width": 140},
		{"label": _("Shortfall"), "fieldname": "shortfall", "fieldtype": "Currency",
		 "options": "currency", "width": 130},
		{"label": _("Outcome"), "fieldname": "outcome", "fieldtype": "Data", "width": 210},
		{"label": _("Suspends on"), "fieldname": "suspends_on", "fieldtype": "Date", "width": 115},
		{"label": _("Paid on time"), "fieldname": "paid_on_time", "fieldtype": "Data", "width": 105},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link",
		 "options": "Currency", "width": 90},
	]


def _summary(rows) -> list[dict]:
	"""Tiles above the table. Money is never summed across currencies."""
	if not rows:
		return []
	at_risk = [r for r in rows if r.get("suspends_on")]
	tiles = [
		{"label": _("Teams projected"), "value": len(rows), "datatype": "Int"},
		{"label": _("Suspending"), "value": len(at_risk), "datatype": "Int",
		 "indicator": "Red" if at_risk else "Green"},
	]
	by_currency: dict = {}
	for row in rows:
		if row.get("currency"):
			by_currency.setdefault(row["currency"], 0.0)
			by_currency[row["currency"]] += frappe.utils.flt(row.get("projected_total"))
	for currency, total in sorted(by_currency.items()):
		tiles.append(
			{"label": _("Projected {0}").format(currency), "value": total,
			 "datatype": "Currency", "currency": currency}
		)
	return tiles


def _batch_note(batch: str) -> str | None:
	"""Say which batch is on screen, when it ran, and whether it finished."""
	doc = frappe.db.get_value(
		"Billing Projection Batch", batch,
		["as_of", "batch_state", "teams_projected", "teams_expected", "sampled", "sample_size", "note"],
		as_dict=True,
	)
	if not doc:
		return None

	parts = [_("Projected {0}").format(frappe.utils.format_date(doc.as_of))]
	if doc.batch_state == "Partial":
		parts.append(
			_("<b>Incomplete</b> — {0} of {1} teams. The rows are real; the cohort is not.").format(
				doc.teams_projected, doc.teams_expected
			)
		)
	if doc.sampled:
		# An extrapolated figure must never be read as a measured one.
		parts.append(
			_("<b>Extrapolated from a sample of {0}</b> — totals are estimates.").format(
				doc.sample_size
			)
		)
	return f'<div class="text-muted">{" · ".join(parts)}</div>'


def _nothing_projected(filters) -> str:
	"""The empty state carries the next step, because there is always one."""
	months = frappe.utils.cint(filters.get("months")) or 1
	sizing = cohort.estimate(_cohort_filters(filters), months)

	if sizing.within_budget:
		return _(
			'<div class="text-muted">No projection yet for this cohort — '
			"{0} teams over {1} month(s), about {2}s. Use <b>Project this cohort</b> to run one."
			"</div>"
		).format(sizing.teams, sizing.months, round(sizing.estimated_seconds))

	hints = cohort.narrowing_hints(_cohort_filters(filters))
	return _(
		'<div class="text-muted"><b>This cohort is too large to project.</b><br>'
		"{0} teams over {1} month(s) would take about {2}s, against a budget of {3}s.<br>"
		"Narrow it by {4}, shorten the range, or take a sample.</div>"
	).format(
		sizing.teams, sizing.months,
		round(sizing.estimated_seconds), sizing.budget_seconds,
		", ".join(hints) or _("adding a filter"),
	)


def _cohort_filters(filters) -> dict:
	return {
		key: filters.get(key)
		for key in ("currency", "country", "cluster", "trust_tier_level", "collection_mode")
		if filters.get(key)
	}
