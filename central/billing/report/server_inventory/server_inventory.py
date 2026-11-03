# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import Counter

from frappe import _

from central.billing.report._currency import split_currency_columns
from central.billing.report._inventory import FREE_CREDITS, FUNDING_CLASSES, INTERNAL, PAID, TRIAL, Inventory
from central.billing.report._paging import first_rows

MONEY_FIELDS = ("list_rate", "revenue")


def execute(filters: dict | None = None):
	"""Every live server, who funds it, what it lists at, what it earns and its share of the metal cost."""
	filters = filters or {}
	inventory = Inventory(filters)
	rows = [_row(server) for server in inventory.servers if _matches(server, filters)]
	columns = split_currency_columns(get_columns(), rows, MONEY_FIELDS)
	chart, summary = get_chart(rows), get_summary(rows)
	rows, message = first_rows(rows, get_message(rows))
	return columns, rows, message, chart, summary


def _matches(server, filters: dict) -> bool:
	return not filters.get("funding") or server.funding == filters["funding"]


def _row(server) -> dict:
	return {
		"server": server.name,
		"title": server.title,
		"team": server.team,
		"team_name": server.team_name,
		"region": server.region,
		"status": server.status,
		"funding": _(server.funding),
		"funding_class": server.funding,
		"plan": server.plan,
		"vcpus": server.vcpus,
		"memory_gib": server.memory_gib,
		"disk_gib": server.disk_gib,
		"cost": server.cost,
		"cost_currency": "INR",
		"currency": server.currency,
		"list_rate": server.list_rate,
		"revenue": server.revenue,
		"margin": server.margin,
	}


def get_message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No live servers match these filters.")
	if any(row["margin"] is None for row in rows):
		return _("Some servers bill in USD. Enter a USD to INR rate to see their margin.")
	return None


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	counts = Counter(row["funding_class"] for row in rows)
	present = [funding for funding in FUNDING_CLASSES if counts[funding]]
	return {
		"data": {
			"labels": [_(funding) for funding in present],
			"datasets": [{"name": _("Servers"), "values": [counts[funding] for funding in present]}],
		},
		"type": "donut",
	}


def get_summary(rows: list[dict]) -> list[dict]:
	counts = Counter(row["funding_class"] for row in rows)
	indicators = {PAID: "Green", FREE_CREDITS: "Orange", TRIAL: "Blue", INTERNAL: "Grey"}
	return [
		{
			"label": _("{0} Servers").format(_(funding)),
			"value": counts[funding],
			"datatype": "Int",
			"indicator": indicators[funding],
		}
		for funding in FUNDING_CLASSES
	]


def get_columns() -> list[dict]:
	return [
		{
			"label": _("Server"),
			"fieldname": "server",
			"fieldtype": "Link",
			"options": "Virtual Machine",
			"width": 130,
		},
		{"label": _("Title"), "fieldname": "title", "fieldtype": "Data", "width": 150},
		{"label": _("Team"), "fieldname": "team", "fieldtype": "Link", "options": "Team", "width": 120},
		{"label": _("Team Name"), "fieldname": "team_name", "fieldtype": "Data", "width": 160},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Link", "options": "Region", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Funding"), "fieldname": "funding", "fieldtype": "Data", "width": 110},
		{"label": _("Plan"), "fieldname": "plan", "fieldtype": "Link", "options": "Plan", "width": 120},
		{"label": _("vCPUs"), "fieldname": "vcpus", "fieldtype": "Float", "precision": 2, "width": 80},
		{
			"label": _("Memory (GiB)"),
			"fieldname": "memory_gib",
			"fieldtype": "Float",
			"precision": 1,
			"width": 110,
		},
		{
			"label": _("Disk (GiB)"),
			"fieldname": "disk_gib",
			"fieldtype": "Float",
			"precision": 0,
			"width": 100,
		},
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
			"label": _("List Rate"),
			"fieldname": "list_rate",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Revenue"),
			"fieldname": "revenue",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Margin (INR)"),
			"fieldname": "margin",
			"fieldtype": "Currency",
			"options": "cost_currency",
			"width": 130,
		},
	]
