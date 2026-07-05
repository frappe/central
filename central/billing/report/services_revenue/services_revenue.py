# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Services revenue — billed revenue by product family.

One row per (family, currency): revenue grouped by the line's **Plan Category**
(VM Plans, AI Tokens, Emails, PDF Generation, Storage, …), so compute sits next to
each consumer service and you can read what every product line earns. A line's
family is resolved from its plan's category; lines whose plan can't be resolved
fall back to their resource type.

Revenue is per currency and never summed across currencies; the share % is each
family's slice of its own currency's total.
"""

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._revenue import billable_line_items

# Composed configs mint no Plan, so their recurring compute line carries no plan to
# resolve a family from — it still belongs to the compute family (ADR 0009).
VM_COMPUTE_FAMILY = "VM Plans"


def execute(filters: dict | None = None):
	filters = filters or {}
	columns = get_columns()
	rows = get_data(filters)
	chart = get_chart(rows)
	summary = get_summary(rows)
	return columns, rows, None, chart, summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Service / Family"), "fieldname": "family", "fieldtype": "Data", "width": 200},
		{"label": _("Kind"), "fieldname": "kind", "fieldtype": "Data", "width": 110},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 90},
		{"label": _("Revenue"), "fieldname": "revenue", "fieldtype": "Currency", "options": "currency", "width": 160},
		{"label": _("Share %"), "fieldname": "share", "fieldtype": "Percent", "width": 100},
	]


def _plan_family_map(plans: set[str]) -> dict[str, str]:
	"""plan name → Plan Category, for the plans present in the lines."""
	plans = {p for p in plans if p}
	if not plans:
		return {}
	return {
		p.name: p.category
		for p in frappe.get_all(
			"Plan", filters={"name": ["in", list(plans)]}, fields=["name", "category"]
		)
		if p.category
	}


def _metered_resource_family_map() -> dict[str, str]:
	"""resource_type → metered Plan Category, so a service line that carries only a
	resource type (metered overage mints no plan on the line) still groups under its
	product family — Tokens → AI Tokens, PDF → PDF Generation, Emails → Emails."""
	metered = {
		c.name for c in frappe.get_all(
			"Plan Category", filters={"billing_type": "Metered"}, fields=["name"]
		)
	}
	out: dict[str, str] = {}
	for r in frappe.get_all(
		"Plan Category Resource Type", fields=["parent", "resource_type"]
	):
		if r.parent in metered:
			out.setdefault(r.resource_type, r.parent)
	return out


def get_data(filters: dict) -> list[dict]:
	lines = billable_line_items(filters)
	family_of_plan = _plan_family_map({line["plan"] for line in lines})
	family_of_rt = _metered_resource_family_map()

	agg: dict[tuple, dict] = {}
	for line in lines:
		# Resolve the family: the plan's category first, then the resource type's
		# metered family, then compute for a plan-less recurring line, else the raw
		# resource type / "Other".
		family = (
			family_of_plan.get(line["plan"])
			or family_of_rt.get(line["resource_type"])
			or (VM_COMPUTE_FAMILY if line["recurring"]
				else line["resource_type"].title() if line["resource_type"]
				else _("Other"))
		)
		g = agg.setdefault((family, line["currency"]), {"revenue": 0.0, "recurring": False})
		g["revenue"] += line["amount"]
		g["recurring"] = g["recurring"] or line["recurring"]

	currency_total: dict[str, float] = {}
	for (_family, currency), g in agg.items():
		currency_total[currency] = currency_total.get(currency, 0.0) + g["revenue"]

	rows = []
	for (family, currency), g in agg.items():
		total = currency_total.get(currency) or 0.0
		rows.append({
			"family": family, "kind": _("Recurring") if g["recurring"] else _("Usage"),
			"currency": currency, "revenue": flt(g["revenue"], 2),
			"share": flt(g["revenue"] / total * 100, 2) if total else 0.0,
		})
	rows.sort(key=lambda r: (r["currency"], -r["revenue"]))
	return rows


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	# A single-currency run reads cleanest as a family share pie; with more than one
	# currency, group revenue by family with one bar per currency.
	currencies = sorted({r["currency"] for r in rows})
	families = sorted({r["family"] for r in rows})
	if len(currencies) == 1:
		crows = [r for r in rows if r["currency"] == currencies[0]]
		return {
			"data": {"labels": [r["family"] for r in crows],
					 "datasets": [{"name": _("Revenue"), "values": [r["revenue"] for r in crows]}]},
			"type": "pie",
		}
	by_key = {(r["family"], r["currency"]): r["revenue"] for r in rows}
	datasets = [
		{"name": _("Revenue ({0})").format(currency),
		 "values": [flt(by_key.get((f, currency), 0.0), 2) for f in families]}
		for currency in currencies
	]
	return {"data": {"labels": families, "datasets": datasets}, "type": "bar"}


def get_summary(rows: list[dict]) -> list[dict]:
	summary = []
	for currency in sorted({r["currency"] for r in rows}):
		crows = [r for r in rows if r["currency"] == currency]
		total = sum(flt(r["revenue"]) for r in crows)
		top = max(crows, key=lambda r: r["revenue"])
		summary.append({"label": _("Revenue ({0})").format(currency), "value": flt(total, 2),
						"datatype": "Float", "indicator": "green"})
		summary.append({"label": _("Top Service ({0})").format(currency),
						"value": f"{top['family']} · {top['share']}%", "datatype": "Data"})
	return summary
