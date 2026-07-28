# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""MRR & YTD revenue — the monthly revenue trend with a year-to-date running total.

One row per (month, currency). **MRR** is the recurring run-rate — the sum of
flat-rate `bundle` line items for the month; **Usage & Services** is everything
else (metered overage, consumer services, add-ons); **Revenue** is the two
together (pre-tax billed value). **YTD Revenue** is the cumulative revenue within
the calendar year, reset each January.

Money is never summed across currencies — a team bills in one currency, and INR
and USD each carry their own MRR/YTD line and their own trend line on the chart.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from central.billing.report._revenue import billable_line_items


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows = get_data(filters)
	chart = get_chart(rows)
	summary = get_summary(rows)
	return columns, rows, None, chart, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 110},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 90},
		{
			"label": _("MRR (Recurring)"),
			"fieldname": "mrr",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("Usage & Services"),
			"fieldname": "usage",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("Revenue"),
			"fieldname": "revenue",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("YTD Revenue"),
			"fieldname": "ytd",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
	]


def _month_key(period_start) -> str:
	d = getdate(period_start)
	return f"{d.year:04d}-{d.month:02d}"


def get_data(filters: dict) -> list[dict]:
	# Aggregate line amounts into (month, currency) → recurring vs usage.
	agg: dict[tuple, dict] = {}
	for line in billable_line_items(filters):
		if not line["period_start"]:
			continue
		key = (_month_key(line["period_start"]), line["currency"])
		g = agg.setdefault(key, {"mrr": 0.0, "usage": 0.0})
		g["mrr" if line["recurring"] else "usage"] += line["amount"]

	rows = []
	for (month, currency), g in agg.items():
		revenue = g["mrr"] + g["usage"]
		rows.append(
			{
				"month": month,
				"currency": currency,
				"mrr": flt(g["mrr"], 2),
				"usage": flt(g["usage"], 2),
				"revenue": flt(revenue, 2),
			}
		)
	rows.sort(key=lambda r: (r["currency"], r["month"]))

	# Year-to-date running total per currency, reset at each calendar-year boundary.
	running: dict[tuple, float] = {}
	for r in rows:
		year = r["month"][:4]
		acc = running.get((r["currency"], year), 0.0) + r["revenue"]
		running[(r["currency"], year)] = acc
		r["ytd"] = flt(acc, 2)
	return rows


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	months = sorted({r["month"] for r in rows})
	currencies = sorted({r["currency"] for r in rows})
	by_key = {(r["month"], r["currency"]): r["revenue"] for r in rows}
	datasets = [
		{
			"name": _("Revenue ({0})").format(currency),
			"values": [flt(by_key.get((m, currency), 0.0), 2) for m in months],
		}
		for currency in currencies
	]
	return {
		"data": {"labels": months, "datasets": datasets},
		"type": "line",
		"lineOptions": {"regionFill": 1},
	}


def get_summary(rows: list[dict]) -> list[dict]:
	# Headline the latest month's MRR and the year's YTD, per currency.
	latest_month = max((r["month"] for r in rows), default=None)
	summary = []
	for currency in sorted({r["currency"] for r in rows}):
		mrr = sum(flt(r["mrr"]) for r in rows if r["currency"] == currency and r["month"] == latest_month)
		ytd = max((flt(r["ytd"]) for r in rows if r["currency"] == currency), default=0.0)
		summary.append(
			{
				"label": _("MRR ({0})").format(currency),
				"value": flt(mrr, 2),
				"datatype": "Float",
				"indicator": "green",
			}
		)
		summary.append(
			{
				"label": _("YTD Revenue ({0})").format(currency),
				"value": flt(ytd, 2),
				"datatype": "Float",
				"indicator": "blue",
			}
		)
	return summary
