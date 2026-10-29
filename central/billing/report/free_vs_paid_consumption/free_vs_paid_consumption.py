# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from central.billing.report._columns import column, inr
from central.billing.report._economics import to_inr
from central.billing.report._inventory import FUNDING_CLASSES, PAID, Inventory
from central.billing.report._telemetry import Telemetry


def execute(filters: dict | None = None):
	"""What servers that pay nothing cost us, beside the ones that pay, per machine or region."""
	filters = filters or {}
	inventory = Inventory(filters)
	usage = Telemetry().servers(inventory.servers)
	by_machine = (filters.get("group_by") or "Machine") == "Machine"
	hosts = dict(
		frappe.get_all(
			"Metal Server",
			fields=["atlas_host_id", "name"],
			filters={"atlas_host_id": ["is", "set"]},
			as_list=True,
		)
	)

	groups: dict = {}
	for server in inventory.servers:
		where = (
			(hosts.get(server.atlas_host_id) or _("Unplaced ({0})").format(server.region))
			if by_machine
			else server.region
		)
		row = groups.setdefault((where, server.funding), _empty(where, server))
		_add(row, server, usage.get(server.name))
	rows = sorted(groups.values(), key=lambda r: (r["where"], FUNDING_CLASSES.index(r["funding_class"])))
	return get_columns(by_machine), rows, _message(), _chart(rows), _summary(rows)


def _empty(where: str, server) -> dict:
	return {
		"where": where,
		"funding_class": server.funding,
		"funding": _(server.funding),
		"inr": "INR",
		"servers": 0,
		"vcpus": 0.0,
		"memory_gib": 0.0,
		"used_vcpus": None,
		"used_memory_gib": None,
		"revenue": 0.0,
		"cost": 0.0,
	}


def _add(row: dict, server, measured: dict | None) -> None:
	row["servers"] += 1
	row["vcpus"] += server.vcpus
	row["memory_gib"] += server.memory_gib
	row["cost"] += server.cost
	if server.funding == PAID:
		row["revenue"] += flt(to_inr(server.list_rate, server.currency))
	if measured:
		row["used_vcpus"] = flt(row["used_vcpus"]) + server.vcpus * measured["cpu_percent"] / 100
		row["used_memory_gib"] = flt(row["used_memory_gib"]) + measured["memory_used_gib"]


def _message() -> str:
	return _(
		"Cost is each server's vCPU share of its region's bare metal per month. Revenue counts paying customers at their monthly price. Used counts servers that run the Pilot agent."
	)


def _chart(rows: list[dict]) -> dict | None:
	if not rows:
		return None
	totals = {}
	for row in rows:
		totals[row["funding"]] = totals.get(row["funding"], 0) + row["cost"]
	return {
		"data": {
			"labels": list(totals),
			"datasets": [{"name": _("Bare metal cost"), "values": [flt(v, 2) for v in totals.values()]}],
		},
		"type": "donut",
	}


def _summary(rows: list[dict]) -> list[dict]:
	free = [row for row in rows if row["funding_class"] != PAID]
	return [
		{
			"label": _("Servers Not Paying"),
			"value": sum(row["servers"] for row in free),
			"datatype": "Int",
			"indicator": "Orange",
		},
		{
			"label": _("vCPUs Not Paying"),
			"value": flt(sum(row["vcpus"] for row in free), 1),
			"datatype": "Float",
		},
		{
			"label": _("Their Cost per Month (INR)"),
			"value": sum(row["cost"] for row in free),
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Red",
		},
		{
			"label": _("Paying Revenue per Month (INR)"),
			"value": sum(row["revenue"] for row in rows),
			"datatype": "Currency",
			"currency": "INR",
			"indicator": "Green",
		},
	]


def get_columns(by_machine: bool) -> list[dict]:
	return [
		column(_("Machine") if by_machine else _("Region"), "where", "Data", 160),
		column(_("Who Pays"), "funding", "Data", 150),
		column(_("Servers"), "servers", "Int", 80),
		column(_("vCPUs"), "vcpus", "Float", 80, precision=1),
		column(_("vCPUs Used"), "used_vcpus", "Float", 100, precision=2),
		column(_("Memory (GiB)"), "memory_gib", "Float", 110, precision=1),
		column(_("Memory Used (GiB)"), "used_memory_gib", "Float", 140, precision=1),
		inr(_("Revenue per Month (INR)"), "revenue", 160),
		inr(_("Bare Metal Cost per Month (INR)"), "cost", 190),
	]
