# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import flt

from central.billing.report._currency import split_currency_columns
from central.billing.report._inventory import FUNDING_CLASSES, IDLE, PAID, Inventory

MONEY_FIELDS = ("list_value", "revenue")

GROUP_FIELDS = {"Funding": "funding", "Region": "region", "Team": "team"}


def execute(filters: dict | None = None):
	"""Monthly metal cost against cash revenue, grouped by funding, region or team.

	Allocated cost plus the idle capacity row adds up to the whole metal bill."""
	filters = filters or {}
	group_by = filters.get("group_by") or "Funding"
	inventory = Inventory(filters)
	servers = [
		server
		for server in inventory.servers
		if not filters.get("funding") or server.funding == filters["funding"]
	]

	rows = _group(servers, GROUP_FIELDS[group_by])
	if group_by != "Team" and not filters.get("team") and not filters.get("funding"):
		rows += _idle_rows(inventory, group_by)

	columns = split_currency_columns(get_columns(group_by), rows, MONEY_FIELDS)
	return columns, rows, get_message(rows), get_chart(rows), get_summary(rows)


def _group(servers: list, fieldname: str) -> list[dict]:
	groups: dict[tuple, dict] = {}
	for server in servers:
		# A server with no subscription lists at 0, so it joins its group's INR row.
		key = (server.get(fieldname), server.currency or "INR")
		row = groups.setdefault(key, _empty_row(server, fieldname))
		row["servers"] += 1
		row["vcpus"] += server.vcpus
		row["cost"] += server.cost
		row["unpaid_cost"] += server.cost if server.funding != PAID else 0
		row["list_value"] += server.list_rate
		row["revenue"] += server.revenue
		row["margin"] = (
			None if row["margin"] is None or server.margin is None else row["margin"] + server.margin
		)

	rows = list(groups.values())
	if fieldname == "funding":
		rows.sort(key=lambda row: FUNDING_CLASSES.index(row["funding_class"]))
	for row in rows:
		row["margin_percent"] = _margin_percent(row)
	return rows


def _empty_row(server, fieldname: str) -> dict:
	return {
		"group": _(server.funding) if fieldname == "funding" else server.get(fieldname),
		"funding_class": server.funding,
		"team_name": server.team_name if fieldname == "team" else None,
		"currency": server.currency or "INR",
		"cost_currency": "INR",
		"servers": 0,
		"vcpus": 0.0,
		"cost": 0.0,
		"unpaid_cost": 0.0,
		"list_value": 0.0,
		"revenue": 0.0,
		"margin": 0.0,
	}


def _idle_rows(inventory: Inventory, group_by: str) -> list[dict]:
	idle = inventory.idle_rows()
	if group_by == "Funding" and idle:
		idle = [
			{"region": None, "vcpus": sum(r["vcpus"] for r in idle), "cost": sum(r["cost"] for r in idle)}
		]

	return [
		{
			"group": _("{0} (idle)").format(row["region"]) if row["region"] else _(IDLE),
			"funding_class": IDLE,
			"currency": "INR",
			"cost_currency": "INR",
			"servers": 0,
			"vcpus": row["vcpus"],
			"cost": row["cost"],
			"list_value": 0.0,
			"revenue": 0.0,
			"margin": -row["cost"],
			"margin_percent": None,
		}
		for row in idle
		if row["cost"]
	]


def _margin_percent(row: dict) -> float | None:
	if row["margin"] is None or not row["revenue"]:
		return None
	return flt(100 * row["margin"] / (row["margin"] + row["cost"]), 1)


def get_message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No live servers match these filters.")
	if any(row["margin"] is None for row in rows):
		return _("Some servers bill in USD. Enter a USD to INR rate to include them in the margin.")
	return None


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	return {
		"data": {
			"labels": [row["group"] for row in rows],
			"datasets": [
				{"name": _("Metal Cost (INR)"), "values": [flt(row["cost"], 2) for row in rows]},
				{"name": _("Margin (INR)"), "values": [flt(row["margin"], 2) for row in rows]},
			],
		},
		"type": "bar",
	}


def get_summary(rows: list[dict]) -> list[dict]:
	cost = sum(row["cost"] for row in rows)
	priced = [row for row in rows if row["margin"] is not None]
	margin = sum(row["margin"] for row in priced)
	revenue_inr = margin + sum(row["cost"] for row in priced)
	given_away = sum(row.get("unpaid_cost", 0) for row in rows)
	return [
		_inr(_("Metal Cost (INR)"), cost),
		_inr(_("Cash Revenue (INR)"), revenue_inr, "Blue"),
		_inr(_("Margin (INR)"), margin, "Green" if margin >= 0 else "Red"),
		_inr(_("Cost of Unpaid Servers (INR)"), given_away, "Orange"),
	]


def _inr(label: str, value: float, indicator: str | None = None) -> dict:
	return {"label": label, "value": value, "datatype": "Currency", "currency": "INR", "indicator": indicator}


def get_columns(group_by: str) -> list[dict]:
	group = {"label": _(group_by), "fieldname": "group", "fieldtype": "Data", "width": 160}
	if group_by == "Region":
		group.update(fieldtype="Link", options="Region")
	if group_by == "Team":
		group.update(fieldtype="Link", options="Team")

	columns = [group]
	if group_by == "Team":
		columns.append({"label": _("Team Name"), "fieldname": "team_name", "fieldtype": "Data", "width": 160})
	return [
		*columns,
		{"label": _("Servers"), "fieldname": "servers", "fieldtype": "Int", "width": 80},
		{"label": _("vCPUs"), "fieldname": "vcpus", "fieldtype": "Float", "precision": 2, "width": 90},
		{
			"label": _("Metal Cost (INR)"),
			"fieldname": "cost",
			"fieldtype": "Currency",
			"options": "cost_currency",
			"width": 130,
		},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
		{
			"label": _("List Value"),
			"fieldname": "list_value",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Cash Revenue"),
			"fieldname": "revenue",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"label": _("Margin (INR)"),
			"fieldname": "margin",
			"fieldtype": "Currency",
			"options": "cost_currency",
			"width": 130,
		},
		{"label": _("Margin %"), "fieldname": "margin_percent", "fieldtype": "Percent", "width": 90},
	]
