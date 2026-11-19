# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._currency import split_currency_columns
from central.billing.report._inventory import FREE_CREDITS, INTERNAL, PAID, TRIAL, Inventory
from central.billing.report._telemetry import Telemetry

MONEY_FIELDS = ("list_value", "revenue")

FUNDING_COUNTS = {INTERNAL: "internal", TRIAL: "trial", FREE_CREDITS: "free_credits", PAID: "paid"}


def execute(filters: dict | None = None):
	"""Each bare metal machine's monthly cost against what the servers on it pay.

	A machine carries its whole cost, idle part included. Servers whose host Atlas has not
	reported yet sit in one Unplaced row per region, so the rows add up to the metal bill."""
	filters = filters or {}
	inventory = Inventory(filters)
	machines = _machines(filters.get("region"))
	by_host = defaultdict(list)
	for server in inventory.servers:
		by_host[server.atlas_host_id or ""].append(server)

	usage = Telemetry().hosts(machines)
	rows = [
		_machine_row(
			machine, _servers_on(machine, by_host), inventory, usage.get(machine.atlas_host_id) or {}
		)
		for machine in machines
	]
	rows += _unplaced_rows(by_host, inventory)

	columns = split_currency_columns(get_columns(), rows, MONEY_FIELDS)
	return columns, rows, get_message(rows), get_chart(rows), get_summary(rows)


def _servers_on(machine, by_host: dict) -> list:
	# A machine with no host ID yet holds no servers; they stay in the Unplaced row.
	return by_host.pop(machine.atlas_host_id, []) if machine.atlas_host_id else []


def _machines(region: str | None) -> list:
	filters = {"status": "Active"}
	if region:
		filters["region"] = region
	return frappe.get_all(
		"Metal Server",
		filters=filters,
		fields=["name", "region", "vendor", "atlas_host_id", "cost_per_month_inr", "vcpus", "memory_gib"],
		order_by="region, name",
	)


def _machine_row(machine, servers: list, inventory: Inventory, host: dict) -> dict:
	row = _totals(servers, inventory)
	allocated = row["allocated_vcpus"]
	row.update(
		metal_server=machine.name,
		region=machine.region,
		vendor=machine.vendor,
		has_host=bool(machine.atlas_host_id),
		cost=flt(machine.cost_per_month_inr),
		vcpus=flt(machine.vcpus),
		vcpu_used_percent=_percent(allocated, machine.vcpus),
		memory_used_percent=_percent(row.pop("memory_gib"), machine.memory_gib),
		cpu_measured_percent=host.get("cpu_percent"),
		memory_measured_percent=_percent(host["memory_used_gib"], machine.memory_gib)
		if host.get("memory_used_gib")
		else None,
	)
	return _with_margin(row)


def _unplaced_rows(by_host: dict, inventory: Inventory) -> list[dict]:
	"""Servers whose host no Active Metal Server records, one row per region."""
	by_region = defaultdict(list)
	for servers in by_host.values():
		for server in servers:
			by_region[server.region].append(server)

	rows = []
	for region, servers in sorted(by_region.items()):
		row = _totals(servers, inventory)
		row.pop("memory_gib")
		row.update(
			metal_server=None,
			label=_("Unplaced ({0})").format(region),
			region=region,
			has_host=False,
			# Their machine already carries its whole cost, so only their revenue is counted here.
			cost=0.0,
			vcpus=None,
			vcpu_used_percent=None,
			memory_used_percent=None,
		)
		rows.append(_with_margin(row))
	return rows


def _totals(servers: list, inventory: Inventory) -> dict:
	currencies = {server.currency for server in servers if server.currency}
	row = {
		"currency": currencies.pop() if len(currencies) == 1 else "INR",
		"cost_currency": "INR",
		"servers": len(servers),
		"allocated_vcpus": sum(server.vcpus for server in servers),
		"memory_gib": sum(server.memory_gib for server in servers),
		"list_value": sum(server.list_rate for server in servers),
		"revenue": sum(server.revenue for server in servers),
		**{fieldname: 0 for fieldname in FUNDING_COUNTS.values()},
	}
	for server in servers:
		row[FUNDING_COUNTS[server.funding]] += 1

	revenue_inr = [server.revenue_inr for server in servers]
	row["revenue_inr"] = None if None in revenue_inr else sum(revenue_inr)
	return row


def _with_margin(row: dict) -> dict:
	revenue = row.pop("revenue_inr")
	row["margin"] = None if revenue is None else revenue - row["cost"]
	row["margin_percent"] = flt(100 * row["margin"] / revenue, 1) if revenue else None
	return row


def _percent(part, whole) -> float:
	return flt(100 * flt(part) / flt(whole), 1) if flt(whole) else 0.0


def get_message(rows: list[dict]) -> str | None:
	if not rows:
		return _("No active bare metal and no live servers.")

	notes = []
	if any(row["metal_server"] and not row["has_host"] for row in rows):
		notes.append(_("Some machines have no Atlas host ID. Open each one and use Link Atlas Host."))
	if any(not row["metal_server"] for row in rows):
		notes.append(
			_("Some servers have no known host yet. Atlas reports it when a server starts, stops or moves.")
		)
	if any(row["margin"] is None for row in rows):
		notes.append(_("Some servers bill in USD. Enter a USD to INR rate to include them in the margin."))
	return "<br>".join(notes) or None


def get_chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None

	return {
		"data": {
			"labels": [row["metal_server"] or row["label"] for row in rows],
			"datasets": [
				{"name": _("Cost (INR)"), "values": [flt(row["cost"], 2) for row in rows]},
				{"name": _("Margin (INR)"), "values": [flt(row["margin"], 2) for row in rows]},
			],
		},
		"type": "bar",
	}


def get_summary(rows: list[dict]) -> list[dict]:
	machines = [row for row in rows if row["metal_server"]]
	priced = [row for row in rows if row["margin"] is not None]
	margin = sum(row["margin"] for row in priced)
	return [
		{"label": _("Machines"), "value": len(machines), "datatype": "Int"},
		{
			"label": _("Machines in Profit"),
			"value": sum(1 for row in machines if (row["margin"] or 0) > 0),
			"datatype": "Int",
			"indicator": "Green",
		},
		{
			"label": _("Metal Cost (INR)"),
			"value": sum(row["cost"] for row in machines),
			"datatype": "Currency",
			"currency": "INR",
		},
		{
			"label": _("Margin (INR)"),
			"value": margin,
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Green" if margin >= 0 else "Red",
		},
	]


def get_columns() -> list[dict]:
	return [
		_column(_("Metal Server"), "metal_server", "Link", 140, options="Metal Server"),
		_column(_("Unplaced"), "label", "Data", 140),
		_column(_("Region"), "region", "Link", 100, options="Region"),
		_column(_("Vendor"), "vendor", "Data", 90),
		_column(_("Servers"), "servers", "Int", 80),
		_column(_("Paying Customers"), "paid", "Int", 60),
		_column(_("Not Paying Yet"), "free_credits", "Int", 100),
		_column(_("Our Own Teams"), "internal", "Int", 80),
		_column(_("Free Trials"), "trial", "Int", 60),
		_column(_("vCPUs"), "vcpus", "Float", 70, precision=0),
		_column(_("Allocated vCPUs"), "allocated_vcpus", "Float", 120, precision=2),
		_column(_("vCPU Allocated %"), "vcpu_used_percent", "Percent", 120),
		_column(_("CPU Used %"), "cpu_measured_percent", "Percent", 100),
		_column(_("Memory Allocated %"), "memory_used_percent", "Percent", 140),
		_column(_("Memory Used %"), "memory_measured_percent", "Percent", 120),
		_column(_("Cost (INR)"), "cost", "Currency", 120, options="cost_currency"),
		_column(_("Currency"), "currency", "Link", 80, options="Currency"),
		_column(_("List Value"), "list_value", "Currency", 120, options="currency"),
		_column(_("Cash Revenue"), "revenue", "Currency", 120, options="currency"),
		_column(_("Margin (INR)"), "margin", "Currency", 120, options="cost_currency"),
		_column(_("Margin %"), "margin_percent", "Percent", 90),
	]


def _column(label: str, fieldname: str, fieldtype: str, width: int, **extra) -> dict:
	return {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **extra}
