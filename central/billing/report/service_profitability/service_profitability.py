# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._columns import column, inr
from central.billing.report._economics import VM_SERVICE, BilledMonth


def execute(filters: dict | None = None):
	"""Which services to push, fix, reprice or drop: revenue, cost, margin, customers and usage per service.

	Price and cost per unit read in the service's own unit (vCPU-month for VMs, GB, token, email)."""
	filters = filters or {}
	month = BilledMonth(filters)
	lines = [line for line in month.lines if not filters.get("service") or line.service == filters["service"]]
	by_team = (filters.get("group_by") or "Service") == "Team"
	rows = _group(lines, by_team)
	rows.sort(key=lambda row: row["revenue"], reverse=True)
	return get_columns(by_team), rows, _message(month, rows), _chart(rows), _summary(rows)


def _group(lines: list, by_team: bool) -> list[dict]:
	groups: dict = {}
	for line in lines:
		key = (line.service, line.team if by_team else None)
		row = groups.setdefault(key, _empty(line, by_team))
		row["revenue"] += flt(line.revenue_inr)
		row["cost"] += flt(line.cost_inr)
		row["usage"] += _units(line)
		row["teams"].add(line.team)
		row["unit"] = row["unit"] or (_("vCPU-months") if line.service == VM_SERVICE else line.unit)
		row["unpriced_usd"] = row["unpriced_usd"] or line.revenue_inr is None

	for row in groups.values():
		row["customers"] = len(row.pop("teams"))
		row["gross_profit"] = row["revenue"] - row["cost"]
		row["margin"] = flt(100 * row["gross_profit"] / row["revenue"], 1) if row["revenue"] else None
		row["revenue_per_unit"] = flt(row["revenue"] / row["usage"], 4) if row["usage"] else None
		row["cost_per_unit"] = flt(row["cost"] / row["usage"], 4) if row["usage"] else None
	return list(groups.values())


def _units(line) -> float:
	"""A VM bundle counts in vCPU-months, so VM plans of every size add up; a metered line counts its quantity."""
	if line.service == VM_SERVICE:
		return flt(line.vcpus) * (flt(line.days) + flt(line.hours) / 24) / 30
	return flt(line.quantity)


def _empty(line, by_team: bool) -> dict:
	return {
		"service": line.service,
		"team": line.team if by_team else None,
		"inr": "INR",
		"revenue": 0.0,
		"cost": 0.0,
		"usage": 0.0,
		"unit": None,
		"teams": set(),
		"unpriced_usd": False,
	}


def _message(month: BilledMonth, rows: list[dict]) -> str:
	text = _(
		"Billed for {0}. Cost is the bare metal share for VMs and usage times the Resource Type's cost per unit for the rest; a service whose Resource Type has no cost shows cost 0."
	).format(month.start.strftime("%B %Y"))
	if any(row["unpriced_usd"] for row in rows):
		text += " " + _("USD revenue is left out: set the USD to INR rate in Billing Settings.")
	return text


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	return {
		"data": {
			"labels": [row["service"] for row in rows],
			"datasets": [
				{"name": _("Revenue"), "values": [flt(row["revenue"], 2) for row in rows]},
				{"name": _("Gross Profit"), "values": [flt(row["gross_profit"], 2) for row in rows]},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	revenue = sum(row["revenue"] for row in rows)
	profit = sum(row["gross_profit"] for row in rows)
	return [
		{"label": _("Services Billed"), "value": len({row["service"] for row in rows}), "datatype": "Int"},
		{"label": _("Revenue (INR)"), "value": revenue, "datatype": "Currency", "currency": "INR"},
		{
			"label": _("Gross Profit (INR)"),
			"value": profit,
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Green" if profit >= 0 else "Red",
		},
		{
			"label": _("Gross Margin"),
			"value": f"{flt(100 * profit / revenue, 1) if revenue else 0}%",
			"datatype": "Data",
		},
	]


def get_columns(by_team: bool) -> list[dict]:
	columns = [column(_("Service"), "service", "Data", 160)]
	if by_team:
		columns.append(column(_("Team"), "team", "Link", 130, options="Team"))
	return [
		*columns,
		column(_("Customers"), "customers", "Int", 90),
		column(_("Usage"), "usage", "Float", 110, precision=2),
		column(_("Unit"), "unit", "Data", 100),
		inr(_("Revenue (INR)"), "revenue"),
		inr(_("Direct Cost (INR)"), "cost"),
		inr(_("Gross Profit (INR)"), "gross_profit"),
		column(_("Margin %"), "margin", "Percent", 80),
		column(_("Price per Unit (INR)"), "revenue_per_unit", "Currency", 130, options="inr"),
		column(_("Cost per Unit (INR)"), "cost_per_unit", "Currency", 130, options="inr"),
	]
