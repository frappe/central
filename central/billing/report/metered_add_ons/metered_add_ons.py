# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Metered Add-ons — allowance + per-currency overage, one row per offering (ADR 0012).

A metered add-on is a single-resource `Plan` under a `Metered` `Plan Category`
(ADR 0008). Its scattered truth — the included **allowance** (`Plan Includes.quantity`)
and the **overage rate per currency** (`Catalog Rate`) — is surfaced here as one legible
row, so the accounts team can answer "what does Email include and cost over that?" at a
glance instead of opening three doctypes.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	add_ons = _metered_add_ons()
	currencies = _currencies(add_ons)
	columns = _columns(currencies)
	data = [_row(a, currencies) for a in add_ons]
	return columns, data


def _metered_add_ons() -> list[dict]:
	"""Active single-resource Plans under a Metered category, with their allowance +
	per-currency global overage rate."""
	metered_cats = frappe.get_all("Plan Category", filters={"billing_type": "Metered"}, pluck="name")
	if not metered_cats:
		return []

	plans = frappe.get_all(
		"Plan",
		filters={"category": ["in", metered_cats], "is_active": 1},
		fields=["name", "title"],
		order_by="title asc",
	)
	if not plans:
		return []
	plan_names = [p.name for p in plans]

	includes_by_plan: dict[str, list] = {}
	for inc in frappe.get_all(
		"Plan Includes",
		filters={"parent": ["in", plan_names]},
		fields=["parent", "resource_type", "quantity", "unit"],
	):
		includes_by_plan.setdefault(inc.parent, []).append(inc)

	# Global (blank-cluster) overage rate per currency — what the add-on charges per unit.
	rates_by_plan: dict[str, dict] = {}
	for rate in frappe.get_all(
		"Catalog Rate",
		filters={"priced_doctype": "Plan", "priced_for": ["in", plan_names], "cluster": ["in", ["", None]]},
		fields=["priced_for", "currency", "rate"],
	):
		rates_by_plan.setdefault(rate.priced_for, {})[rate.currency] = rate.rate

	add_ons = []
	for p in plans:
		includes = includes_by_plan.get(p.name, [])
		if len(includes) != 1:
			continue  # only single-resource plans are metered add-ons (ADR 0008)
		inc = includes[0]
		add_ons.append(
			{
				"plan": p.name,
				"title": p.title,
				"resource_type": inc.resource_type,
				"allowance": flt(inc.quantity),
				"unit": inc.unit,
				"rates": rates_by_plan.get(p.name, {}),
			}
		)
	return add_ons


def _currencies(add_ons: list[dict]) -> list[str]:
	"""Every currency any add-on is priced in, so each gets a column."""
	seen: set[str] = set()
	for a in add_ons:
		seen.update(a["rates"])
	return sorted(seen)


def _columns(currencies: list[str]) -> list[dict]:
	columns = [
		{"label": _("Add-on"), "fieldname": "plan", "fieldtype": "Link", "options": "Plan", "width": 200},
		{"label": _("Resource"), "fieldname": "resource_type", "fieldtype": "Data", "width": 120},
		{
			"label": _("Allowance"),
			"fieldname": "allowance",
			"fieldtype": "Float",
			"width": 110,
			"precision": 2,
		},
		{"label": _("Unit"), "fieldname": "unit", "fieldtype": "Data", "width": 90},
	]
	for currency in currencies:
		columns.append(
			{
				"label": _("Overage / {0}").format(currency),
				"fieldname": f"overage_{currency.lower()}",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 130,
			}
		)
	return columns


def _row(add_on: dict, currencies: list[str]) -> dict:
	row = {
		"plan": add_on["plan"],
		"resource_type": add_on["resource_type"],
		"allowance": add_on["allowance"],
		"unit": add_on["unit"],
	}
	for currency in currencies:
		row[f"overage_{currency.lower()}"] = add_on["rates"].get(currency)
	return row
