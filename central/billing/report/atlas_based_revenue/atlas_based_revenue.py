# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Atlas-based revenue — where billed revenue is earned, by Atlas instance / region.

An Asset's `cluster` is the Atlas instance it runs on (one Atlas instance is one
region/cluster), so grouping line-item revenue by cluster is revenue-by-Atlas. One
row per (cluster, currency): the revenue provisioned on that Atlas instance, its
human region label, and its share of that currency's total. Recurring (bundle) vs
usage is split out so you can see a region's compute base separately from its
metered spend.

Revenue is grouped per currency and never summed across them; the share % is each
Atlas instance's slice of its own currency's total, so the percentages add to 100
within a currency.
"""

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.regions import region_label
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
		{"label": _("Cluster"), "fieldname": "cluster", "fieldtype": "Data", "width": 130},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 180},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 90},
		{
			"label": _("Recurring"),
			"fieldname": "recurring",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
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
		{"label": _("Share %"), "fieldname": "share", "fieldtype": "Percent", "width": 100},
	]


def get_data(filters: dict) -> list[dict]:
	agg: dict[tuple, dict] = {}
	for line in billable_line_items(filters):
		cluster = line["cluster"] or _("(unassigned)")
		g = agg.setdefault((cluster, line["currency"]), {"recurring": 0.0, "usage": 0.0})
		g["recurring" if line["recurring"] else "usage"] += line["amount"]

	# Per-currency totals, for the share column.
	currency_total: dict[str, float] = {}
	for (_cluster, currency), g in agg.items():
		currency_total[currency] = currency_total.get(currency, 0.0) + g["recurring"] + g["usage"]

	rows = []
	for (cluster, currency), g in agg.items():
		revenue = g["recurring"] + g["usage"]
		total = currency_total.get(currency) or 0.0
		rows.append(
			{
				"cluster": cluster,
				"region": region_label(cluster) or cluster,
				"currency": currency,
				"recurring": flt(g["recurring"], 2),
				"usage": flt(g["usage"], 2),
				"revenue": flt(revenue, 2),
				"share": flt(revenue / total * 100, 2) if total else 0.0,
			}
		)
	rows.sort(key=lambda r: (r["currency"], -r["revenue"]))
	return rows


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	clusters = sorted({r["cluster"] for r in rows})
	currencies = sorted({r["currency"] for r in rows})
	by_key = {(r["cluster"], r["currency"]): r["revenue"] for r in rows}
	datasets = [
		{
			"name": _("Revenue ({0})").format(currency),
			"values": [flt(by_key.get((c, currency), 0.0), 2) for c in clusters],
		}
		for currency in currencies
	]
	# One bar per cluster, grouped by currency (a single-currency run reads as a
	# plain revenue-by-cluster bar).
	return {"data": {"labels": clusters, "datasets": datasets}, "type": "bar"}


def get_summary(rows: list[dict]) -> list[dict]:
	summary = []
	for currency in sorted({r["currency"] for r in rows}):
		crows = [r for r in rows if r["currency"] == currency]
		total = sum(flt(r["revenue"]) for r in crows)
		top = max(crows, key=lambda r: r["revenue"])
		summary.append(
			{
				"label": _("Revenue ({0})").format(currency),
				"value": flt(total, 2),
				"datatype": "Float",
				"indicator": "green",
			}
		)
		summary.append(
			{
				"label": _("Top Cluster ({0})").format(currency),
				"value": f"{top['cluster']} · {top['share']}%",
				"datatype": "Data",
			}
		)
	return summary
