# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict

from frappe import _
from frappe.utils import flt

from central.billing.report._columns import column, inr
from central.billing.report._economics import VM_SERVICE, BilledMonth
from central.billing.report._inventory import Inventory
from central.billing.report._telemetry import Telemetry

GROUP_FIELDS = {"Team": "team", "Server": "server", "Service": "service"}


def execute(filters: dict | None = None):
	"""Who makes us money: revenue by service, what it cost us and what is left, per team, server or service.

	Filter one team to see its servers and services."""
	filters = filters or {}
	group_by = filters.get("group_by") or "Team"
	month = BilledMonth(filters)
	inventory = Inventory({"team": filters.get("team")})
	usage = Telemetry().servers(inventory.servers)

	rows = _group(month.lines, GROUP_FIELDS[group_by])
	_add_allocation(rows, group_by, inventory, usage)
	rows.sort(key=lambda row: row["gross_profit"])
	return get_columns(group_by), rows, _message(month, rows), _chart(rows), _summary(rows)


def _group(lines: list, field: str) -> list[dict]:
	groups: dict = {}
	for line in lines:
		key = line.get(field) or _("Not a server")
		row = groups.setdefault(key, _empty(key, line, field))
		revenue = flt(line.revenue_inr)
		row["vm_revenue" if line.service == VM_SERVICE else "service_revenue"] += revenue
		row["revenue"] += revenue
		row["cost"] += flt(line.cost_inr)
		row["unpriced_usd"] = row["unpriced_usd"] or line.revenue_inr is None
	for row in groups.values():
		row["gross_profit"] = row["revenue"] - row["cost"]
		row["margin"] = flt(100 * row["gross_profit"] / row["revenue"], 1) if row["revenue"] else None
	return list(groups.values())


def _empty(key: str, line, field: str) -> dict:
	return {
		"group": key,
		"team": line.team,
		"inr": "INR",
		"vm_revenue": 0.0,
		"service_revenue": 0.0,
		"revenue": 0.0,
		"cost": 0.0,
		"unpriced_usd": False,
		"service": line.service if field == "service" else None,
	}


def _add_allocation(rows: list[dict], group_by: str, inventory: Inventory, usage: dict) -> None:
	"""Live allocation and measured use beside the money: vCPUs, CPU used and memory used."""
	by_key = defaultdict(list)
	for server in inventory.servers:
		key = {"Team": server.team, "Server": server.name}.get(group_by)
		by_key[key].append(server)

	for row in rows:
		servers = by_key.get(row["group"], [])
		measured = [usage[s.name] for s in servers if s.name in usage]
		row["servers"] = len(servers)
		row["allocated_vcpus"] = sum(s.vcpus for s in servers)
		row["allocated_memory_gib"] = sum(s.memory_gib for s in servers)
		row["funding"] = _(servers[0].funding) if servers else None
		row["cpu_used_vcpus"] = (
			flt(sum(s.vcpus * usage[s.name]["cpu_percent"] / 100 for s in servers if s.name in usage), 2)
			if measured
			else None
		)
		row["memory_used_gib"] = flt(sum(m["memory_used_gib"] for m in measured), 1) if measured else None


def _message(month: BilledMonth, rows: list[dict]) -> str:
	text = _("Billed for {0}. Used CPU and memory come from servers that run the Pilot agent.").format(
		month.start.strftime("%B %Y")
	)
	if any(row["unpriced_usd"] for row in rows):
		text += " " + _("USD revenue is left out: set the USD to INR rate in Billing Settings.")
	return text


def _chart(rows: list[dict]) -> dict | None:
	top = sorted(rows, key=lambda row: row["revenue"], reverse=True)[:15]
	if not top:
		return None
	return {
		"data": {
			"labels": [row["group"] for row in top],
			"datasets": [
				{"name": _("Revenue"), "values": [flt(row["revenue"], 2) for row in top]},
				{"name": _("Cost"), "values": [flt(row["cost"], 2) for row in top]},
			],
		},
		"type": "bar",
	}


def _summary(rows: list[dict]) -> list[dict]:
	revenue = sum(row["revenue"] for row in rows)
	profit = sum(row["gross_profit"] for row in rows)
	return [
		{"label": _("Revenue (INR)"), "value": revenue, "datatype": "Currency", "currency": "INR"},
		{
			"label": _("Direct Cost (INR)"),
			"value": sum(row["cost"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
		},
		{
			"label": _("Gross Profit (INR)"),
			"value": profit,
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Green" if profit >= 0 else "Red",
		},
		{
			"label": _("Losing Money"),
			"value": sum(1 for row in rows if row["gross_profit"] < 0),
			"datatype": "Int",
			"indicator": "Red",
		},
	]


def get_columns(group_by: str) -> list[dict]:
	link = {"Team": "Team", "Server": "Virtual Machine"}.get(group_by)
	first = column(
		_(group_by), "group", "Link" if link else "Data", 150, **({"options": link} if link else {})
	)
	return [
		first,
		column(_("Who Pays"), "funding", "Data", 130),
		column(_("Servers"), "servers", "Int", 70),
		inr(_("VM Revenue (INR)"), "vm_revenue"),
		inr(_("Services Revenue (INR)"), "service_revenue"),
		inr(_("Revenue (INR)"), "revenue"),
		inr(_("Direct Cost (INR)"), "cost"),
		inr(_("Gross Profit (INR)"), "gross_profit"),
		column(_("Margin %"), "margin", "Percent", 80),
		column(_("vCPUs Allocated"), "allocated_vcpus", "Float", 110, precision=1),
		column(_("vCPUs Used"), "cpu_used_vcpus", "Float", 90, precision=2),
		column(_("Memory Allocated (GiB)"), "allocated_memory_gib", "Float", 150, precision=1),
		column(_("Memory Used (GiB)"), "memory_used_gib", "Float", 130, precision=1),
	]
